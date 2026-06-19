from uuid import UUID

from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.db.session import SessionLocal
from app.modules.processing.tasking import build_processing_service


def process_document_in_session(document_id: str, session: Session) -> None:
    parsed_document_id = UUID(document_id)
    service = build_processing_service(session)
    service.initialize_pipeline(parsed_document_id, updated_by="celery")


@celery_app.task(name="app.modules.processing.initialization.task.process_document.process_document")
def process_document(document_id: str) -> str:
    with SessionLocal() as session:
        try:
            process_document_in_session(document_id, session)
            session.commit()
        except Exception:
            session.rollback()
            raise
    return document_id
