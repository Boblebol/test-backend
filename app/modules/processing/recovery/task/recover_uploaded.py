from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.modules.documents.repository import DocumentRepository
from app.modules.processing.pipeline import PipelineOrchestrator


def recover_stale_uploaded_documents_in_session(
    *,
    session: Session,
    pipeline,
    now: datetime,
    stale_after_hours: int,
    limit: int,
) -> dict:
    cutoff = now - timedelta(hours=stale_after_hours)
    documents = DocumentRepository(session).list_stale_uploaded(cutoff=cutoff, limit=limit)
    enqueued_document_ids: list[str] = []
    failed_document_ids: list[str] = []

    for document in documents:
        try:
            pipeline.enqueue_full_pipeline(document.id)
        except Exception:
            failed_document_ids.append(str(document.id))
            continue
        enqueued_document_ids.append(str(document.id))

    return {
        "matched": len(documents),
        "enqueued": len(enqueued_document_ids),
        "failed": len(failed_document_ids),
        "document_ids": enqueued_document_ids,
        "failed_document_ids": failed_document_ids,
    }


def recover_stale_uploaded_documents(
    *,
    stale_after_hours: int = 24,
    limit: int = 100,
) -> dict:
    from app.db.session import SessionLocal

    with SessionLocal() as session:
        return recover_stale_uploaded_documents_in_session(
            session=session,
            pipeline=PipelineOrchestrator(),
            now=datetime.now(timezone.utc),
            stale_after_hours=stale_after_hours,
            limit=limit,
        )


@celery_app.task(
    name=(
        "app.modules.processing.recovery.task.recover_uploaded."
        "recover_stale_uploaded_documents_task"
    )
)
def recover_stale_uploaded_documents_task(
    *,
    stale_after_hours: int = 24,
    limit: int = 100,
) -> dict:
    return recover_stale_uploaded_documents(
        stale_after_hours=stale_after_hours,
        limit=limit,
    )
