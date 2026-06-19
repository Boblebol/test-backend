from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.db.models import DocumentORM, OrganizationORM, UserORM
from app.domain.enums import DocumentStatus
from app.domain.models import CreateDocumentRecord
from app.modules.documents.repository import DocumentRepository


pytestmark = pytest.mark.integration


def test_document_repository_create_persists_document(
    db_session: Session,
    persisted_org_user: object,
    create_document_record: CreateDocumentRecord,
) -> None:
    state = DocumentRepository(db_session).create(create_document_record)

    row = db_session.get(DocumentORM, create_document_record.id)
    assert row is not None
    assert row.org_id == create_document_record.org_id
    assert row.owner_user_id == create_document_record.owner_user_id
    assert row.storage_key == create_document_record.storage_key
    assert row.status == DocumentStatus.WAITING_UPLOAD.value
    assert state.id == create_document_record.id
    assert state.status is DocumentStatus.WAITING_UPLOAD


def test_document_repository_get_for_org_enforces_org_scope(
    db_session: Session,
    persisted_org_user: object,
    create_document_record: CreateDocumentRecord,
) -> None:
    repository = DocumentRepository(db_session)
    repository.create(create_document_record)

    assert repository.get_for_org(create_document_record.id, create_document_record.org_id) is not None
    assert repository.get_for_org(create_document_record.id, uuid4()) is None


def test_document_repository_update_status_clears_previous_error(
    db_session: Session,
    persisted_org_user: object,
    create_document_record: CreateDocumentRecord,
) -> None:
    repository = DocumentRepository(db_session)
    repository.create(create_document_record)
    repository.mark_failed(create_document_record.id, "TimeoutError", "provider timeout")

    repository.update_status(create_document_record.id, DocumentStatus.READY)

    row = db_session.get(DocumentORM, create_document_record.id)
    assert row is not None
    assert row.status == DocumentStatus.READY.value
    assert row.current_error_type is None
    assert row.current_error_message is None


def test_document_repository_get_by_external_job_id_returns_matching_document(
    db_session: Session,
    persisted_org_user: object,
    create_document_record: CreateDocumentRecord,
) -> None:
    repository = DocumentRepository(db_session)
    document = repository.create(create_document_record)
    repository.set_external_job(document.id, "j_partner_123")
    db_session.flush()

    found = repository.get_by_external_job_id("j_partner_123")

    assert found is not None
    assert found.id == document.id
    assert repository.get_by_external_job_id("j_missing") is None


def test_document_repository_lists_org_page_with_status_filter_and_keyset_cursor(
    db_session: Session,
    persisted_org_user: object,
    create_document_record: CreateDocumentRecord,
) -> None:
    repository = DocumentRepository(db_session)
    base_time = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)
    oldest_uploaded = repository.create(
        replace(
            create_document_record,
            id=uuid4(),
            storage_key=f"orgs/test/documents/{uuid4()}/oldest-uploaded.pdf",
            status=DocumentStatus.UPLOADED,
        )
    )
    middle_uploaded = repository.create(
        replace(
            create_document_record,
            id=uuid4(),
            storage_key=f"orgs/test/documents/{uuid4()}/middle-uploaded.pdf",
            status=DocumentStatus.UPLOADED,
        )
    )
    newest_waiting = repository.create(
        replace(
            create_document_record,
            id=uuid4(),
            storage_key=f"orgs/test/documents/{uuid4()}/newest-waiting.pdf",
            status=DocumentStatus.WAITING_UPLOAD,
        )
    )
    other_org_id = uuid4()
    other_user_id = uuid4()
    db_session.add(OrganizationORM(id=other_org_id, name="Other Org"))
    db_session.add(
        UserORM(
            id=other_user_id,
            org_id=other_org_id,
            email="other@example.com",
            password_hash="hashed-password",
        )
    )
    other_org_uploaded = repository.create(
        replace(
            create_document_record,
            id=uuid4(),
            org_id=other_org_id,
            owner_user_id=other_user_id,
            storage_key=f"orgs/other/documents/{uuid4()}/other-uploaded.pdf",
            status=DocumentStatus.UPLOADED,
        )
    )
    db_session.flush()
    for offset, document in enumerate(
        [oldest_uploaded, middle_uploaded, newest_waiting, other_org_uploaded]
    ):
        row = db_session.get(DocumentORM, document.id)
        assert row is not None
        row.created_at = base_time + timedelta(minutes=offset)
        row.updated_at = base_time + timedelta(minutes=offset)
    db_session.flush()
    middle_row = db_session.get(DocumentORM, middle_uploaded.id)
    assert middle_row is not None

    first_page = repository.list_for_org_page(
        org_id=create_document_record.org_id,
        limit=1,
        status=DocumentStatus.UPLOADED,
    )
    second_page = repository.list_for_org_page(
        org_id=create_document_record.org_id,
        limit=2,
        status=DocumentStatus.UPLOADED,
        cursor=(middle_row.created_at, middle_row.id),
    )

    assert [document.id for document in first_page] == [middle_uploaded.id]
    assert [document.id for document in second_page] == [oldest_uploaded.id]


def test_document_repository_lists_stale_uploaded_documents(
    db_session: Session,
    persisted_org_user: object,
    create_document_record: CreateDocumentRecord,
) -> None:
    repository = DocumentRepository(db_session)
    now = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)
    cutoff = now - timedelta(hours=24)
    stale_uploaded = repository.create(
        replace(
            create_document_record,
            id=uuid4(),
            storage_key=f"orgs/test/documents/{uuid4()}/stale-uploaded.pdf",
            status=DocumentStatus.UPLOADED,
        )
    )
    recent_uploaded = repository.create(
        replace(
            create_document_record,
            id=uuid4(),
            storage_key=f"orgs/test/documents/{uuid4()}/recent-uploaded.pdf",
            status=DocumentStatus.UPLOADED,
        )
    )
    stale_processing = repository.create(
        replace(
            create_document_record,
            id=uuid4(),
            storage_key=f"orgs/test/documents/{uuid4()}/stale-processing.pdf",
            status=DocumentStatus.PROCESSING,
        )
    )
    db_session.flush()
    db_session.get(DocumentORM, stale_uploaded.id).updated_at = cutoff - timedelta(seconds=1)
    db_session.get(DocumentORM, recent_uploaded.id).updated_at = cutoff + timedelta(seconds=1)
    db_session.get(DocumentORM, stale_processing.id).updated_at = cutoff - timedelta(seconds=1)
    db_session.flush()

    documents = repository.list_stale_uploaded(cutoff=cutoff, limit=10)

    assert [document.id for document in documents] == [stale_uploaded.id]
