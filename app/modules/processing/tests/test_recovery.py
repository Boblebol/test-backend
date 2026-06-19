from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from app.db.models import DocumentORM
from app.celery_app import celery_app
from app.domain.enums import DocumentStatus
from app.domain.models import CreateDocumentRecord
from app.modules.documents.repository import DocumentRepository
from app.modules.processing.recovery.task.recover_uploaded import (
    recover_stale_uploaded_documents_in_session,
)


pytestmark = pytest.mark.integration


def test_recover_stale_uploaded_documents_enqueues_full_pipeline(
    db_session: Session,
    persisted_org_user: object,
    create_document_record: CreateDocumentRecord,
) -> None:
    now = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)
    stale_uploaded = create_document(
        db_session,
        create_document_record,
        status=DocumentStatus.UPLOADED,
        updated_at=now - timedelta(hours=25),
    )
    create_document(
        db_session,
        create_document_record,
        status=DocumentStatus.UPLOADED,
        updated_at=now - timedelta(hours=23),
    )
    create_document(
        db_session,
        create_document_record,
        status=DocumentStatus.PROCESSING,
        updated_at=now - timedelta(hours=25),
    )
    pipeline = FakePipelineOrchestrator()

    summary = recover_stale_uploaded_documents_in_session(
        session=db_session,
        pipeline=pipeline,
        now=now,
        stale_after_hours=24,
        limit=100,
    )

    assert pipeline.enqueued_document_ids == [stale_uploaded.id]
    assert summary == {
        "matched": 1,
        "enqueued": 1,
        "failed": 0,
        "document_ids": [str(stale_uploaded.id)],
        "failed_document_ids": [],
    }


def create_document(
    session: Session,
    record: CreateDocumentRecord,
    *,
    status: DocumentStatus,
    updated_at: datetime,
):
    document_id = uuid4()
    document = DocumentRepository(session).create(
        replace(
            record,
            id=document_id,
            storage_key=f"orgs/test/documents/{document_id}/{status.value}.pdf",
            status=status,
        )
    )
    session.flush()
    row = session.get(DocumentORM, document.id)
    assert row is not None
    row.updated_at = updated_at
    session.flush()
    return document


class FakePipelineOrchestrator:
    def __init__(self) -> None:
        self.enqueued_document_ids: list[UUID] = []

    def enqueue_full_pipeline(self, document_id: UUID) -> str:
        self.enqueued_document_ids.append(document_id)
        return f"task-{len(self.enqueued_document_ids)}"


def test_stale_uploaded_recovery_task_is_registered_in_celery_beat() -> None:
    schedule = celery_app.conf.beat_schedule["recover-stale-uploaded-documents"]

    assert schedule["task"] == (
        "app.modules.processing.recovery.task.recover_uploaded."
        "recover_stale_uploaded_documents_task"
    )
    assert schedule["schedule"] == 60 * 60
    assert schedule["kwargs"] == {"stale_after_hours": 24, "limit": 100}
    assert schedule["options"] == {"queue": "documents.recovery"}
