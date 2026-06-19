from uuid import UUID

from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.domain.enums import ProcessingStepName
from app.modules.processing.ocr.ocr import ocr
from app.modules.processing.tasking import build_processing_service, run_step, run_with_session


def ocr_document_in_session(
    document_id: str,
    session: Session,
    ocr_func=ocr,
    task_context=None,
    publisher=None,
) -> None:
    parsed_document_id = UUID(document_id)
    service = build_processing_service(session, publisher=publisher)

    def execute_step() -> None:
        text = ocr_func()
        service.store_ocr_result(parsed_document_id, text)
        if not text.strip():
            raise ValueError("OCR result is empty")

    run_step(
        parsed_document_id,
        service,
        ProcessingStepName.OCR,
        execute_step,
        task_context=task_context,
    )


@celery_app.task(
    bind=True,
    max_retries=3,
    name="app.modules.processing.ocr.task.ocr.ocr_document",
)
def ocr_document(self, document_id: str) -> str:
    run_with_session(ocr_document_in_session, document_id, task_context=self)
    return document_id
