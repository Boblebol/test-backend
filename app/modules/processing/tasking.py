from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.enums import ProcessingStepName
from app.modules.documents.repository import DocumentRepository
from app.modules.processing.progress import (
    CollectingProgressPublisher,
    build_redis_progress_publisher,
    publish_collected_events,
)
from app.modules.processing.result_repository import ExtractedDataRepository
from app.modules.processing.service import ProcessingService
from app.modules.processing.step_repository import ProcessingStepRepository


RETRYABLE_ERRORS: dict[ProcessingStepName, type[Exception]] = {
    ProcessingStepName.OCR: TimeoutError,
    ProcessingStepName.METADATA: ValueError,
    ProcessingStepName.CHUNKING: ValueError,
    ProcessingStepName.EXTERNAL_CALL: ConnectionError,
}


def build_processing_service(session: Session, publisher=None) -> ProcessingService:
    return ProcessingService(
        documents=DocumentRepository(session),
        steps=ProcessingStepRepository(session),
        extracted_data=ExtractedDataRepository(session),
        publisher=publisher,
    )


def run_step(
    document_id: UUID,
    service: ProcessingService,
    name: ProcessingStepName,
    run_step_func,
    task_context=None,
) -> None:
    service.mark_step_running(document_id, name)
    try:
        run_step_func()
    except Exception as exc:
        if should_retry(name, exc, task_context):
            service.mark_step_retrying(document_id, name, exc)
            raise task_context.retry(
                exc=exc,
                countdown=retry_countdown(task_context.request.retries),
            )
        service.mark_step_failed(document_id, name, exc)
        raise
    service.mark_step_success(document_id, name)


def run_with_session(runner, document_id: str, task_context=None) -> None:
    collected_events = CollectingProgressPublisher()
    from app.db.session import SessionLocal

    with SessionLocal() as session:
        try:
            runner(
                document_id,
                session,
                task_context=task_context,
                publisher=collected_events,
            )
        except Exception:
            session.commit()
            publish_collected_progress(collected_events)
            raise
        else:
            session.commit()
            publish_collected_progress(collected_events)


def should_retry(name: ProcessingStepName, exc: Exception, task_context) -> bool:
    if task_context is None:
        return False
    retryable_error = RETRYABLE_ERRORS[name]
    if not isinstance(exc, retryable_error):
        return False
    return task_context.request.retries < task_context.max_retries


def retry_countdown(retries: int) -> int:
    return min(60, 2**retries)


def publish_collected_progress(collected_events: CollectingProgressPublisher) -> None:
    if not collected_events.events:
        return
    publisher = build_redis_progress_publisher(get_settings().redis_url)
    publish_collected_events(collected_events, publisher)
