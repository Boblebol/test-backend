from uuid import UUID

from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.domain.enums import ProcessingStepName
from app.modules.processing.metadata.metadata import metadata
from app.modules.processing.result_repository import ExtractedDataRepository
from app.modules.processing.tasking import build_processing_service, run_step, run_with_session


def extract_metadata_in_session(
    document_id: str,
    session: Session,
    metadata_func=metadata,
    task_context=None,
    publisher=None,
) -> None:
    parsed_document_id = UUID(document_id)
    service = build_processing_service(session, publisher=publisher)

    def execute_step() -> None:
        extracted = ExtractedDataRepository(session).get(parsed_document_id)
        if extracted is None or extracted.ocr_text is None:
            raise ValueError("OCR result is missing")
        result = metadata_func(extracted.ocr_text)
        service.store_metadata_result(parsed_document_id, result)

    run_step(
        parsed_document_id,
        service,
        ProcessingStepName.METADATA,
        execute_step,
        task_context=task_context,
    )


@celery_app.task(
    bind=True,
    max_retries=3,
    name="app.modules.processing.metadata.task.metadata.extract_metadata",
)
def extract_metadata(self, document_id: str) -> str:
    run_with_session(extract_metadata_in_session, document_id, task_context=self)
    return document_id
