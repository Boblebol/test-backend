from uuid import UUID

from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.domain.enums import ProcessingStepName
from app.modules.processing.external_call.external_call import external_call
from app.modules.processing.result_repository import ExtractedDataRepository
from app.modules.processing.tasking import build_processing_service, run_step, run_with_session


def call_external_partner_in_session(
    document_id: str,
    session: Session,
    external_call_func=external_call,
    task_context=None,
    publisher=None,
) -> None:
    parsed_document_id = UUID(document_id)
    service = build_processing_service(session, publisher=publisher)

    def execute_step() -> None:
        extracted = ExtractedDataRepository(session).get(parsed_document_id)
        if (
            extracted is None
            or extracted.ocr_text is None
            or extracted.metadata_json is None
            or extracted.chunks_json is None
        ):
            raise ValueError("pipeline outputs are missing")
        job_id = external_call_func(
            str(parsed_document_id),
            extracted.ocr_text,
            extracted.metadata_json,
            extracted.chunks_json,
        )
        service.mark_waiting_partner(parsed_document_id, job_id)

    run_step(
        parsed_document_id,
        service,
        ProcessingStepName.EXTERNAL_CALL,
        execute_step,
        task_context=task_context,
    )


@celery_app.task(
    bind=True,
    max_retries=5,
    name="app.modules.processing.external_call.task.external_call.call_external_partner",
)
def call_external_partner(self, document_id: str) -> str:
    run_with_session(call_external_partner_in_session, document_id, task_context=self)
    return document_id
