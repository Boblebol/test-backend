import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ExtractedDataORM, ProcessingStepORM
from app.domain.enums import ProcessingStepName, ProcessingStepStatus
from app.domain.models import CreateDocumentRecord
from app.modules.documents.repository import DocumentRepository
from app.modules.processing.result_repository import ExtractedDataRepository
from app.modules.processing.step_repository import ProcessingStepRepository


pytestmark = pytest.mark.integration


def test_processing_step_repository_upsert_creates_missing_step(
    db_session: Session,
    persisted_org_user: object,
    create_document_record: CreateDocumentRecord,
) -> None:
    DocumentRepository(db_session).create(create_document_record)

    ProcessingStepRepository(db_session).upsert(
        document_id=create_document_record.id,
        name=ProcessingStepName.OCR,
        status=ProcessingStepStatus.PENDING,
        updated_by="unit-test",
    )
    db_session.flush()

    row = db_session.scalar(
        select(ProcessingStepORM).where(
            ProcessingStepORM.document_id == create_document_record.id,
            ProcessingStepORM.name == ProcessingStepName.OCR.value,
        )
    )
    assert row is not None
    assert row.status == ProcessingStepStatus.PENDING.value
    assert row.attempt_count == 0
    assert row.updated_by == "unit-test"


def test_processing_step_repository_upsert_resets_existing_step(
    db_session: Session,
    persisted_org_user: object,
    create_document_record: CreateDocumentRecord,
) -> None:
    DocumentRepository(db_session).create(create_document_record)
    repository = ProcessingStepRepository(db_session)
    repository.upsert(
        document_id=create_document_record.id,
        name=ProcessingStepName.OCR,
        status=ProcessingStepStatus.FAILED,
        updated_by="worker",
    )
    db_session.flush()
    row = db_session.scalar(select(ProcessingStepORM))
    assert row is not None
    row.attempt_count = 3
    row.result_json = {"ocr_text": "old text"}
    row.error_type = "TimeoutError"
    row.error_message = "provider timeout"

    repository.upsert(
        document_id=create_document_record.id,
        name=ProcessingStepName.OCR,
        status=ProcessingStepStatus.PENDING,
        updated_by="manual-retry",
    )

    assert row.status == ProcessingStepStatus.PENDING.value
    assert row.attempt_count == 0
    assert row.result_json is None
    assert row.error_type is None
    assert row.error_message is None
    assert row.updated_by == "manual-retry"


def test_processing_step_repository_stores_current_debug_result(
    db_session: Session,
    persisted_org_user: object,
    create_document_record: CreateDocumentRecord,
) -> None:
    DocumentRepository(db_session).create(create_document_record)
    repository = ProcessingStepRepository(db_session)
    repository.upsert(
        document_id=create_document_record.id,
        name=ProcessingStepName.OCR,
        status=ProcessingStepStatus.RUNNING,
        updated_by="worker",
    )

    repository.set_result(
        document_id=create_document_record.id,
        name=ProcessingStepName.OCR,
        result_json={"ocr_text": "lease raw text"},
    )
    db_session.flush()

    row = db_session.scalar(select(ProcessingStepORM))
    assert row is not None
    assert row.result_json == {"ocr_text": "lease raw text"}


def test_processing_step_repository_mark_retrying_increments_attempt_count(
    db_session: Session,
    persisted_org_user: object,
    create_document_record: CreateDocumentRecord,
) -> None:
    DocumentRepository(db_session).create(create_document_record)
    repository = ProcessingStepRepository(db_session)
    repository.upsert(
        document_id=create_document_record.id,
        name=ProcessingStepName.OCR,
        status=ProcessingStepStatus.RUNNING,
        updated_by="worker",
    )
    db_session.flush()

    repository.mark_retrying(
        document_id=create_document_record.id,
        name=ProcessingStepName.OCR,
        error_type="TimeoutError",
        error_message="provider timeout",
    )
    repository.mark_retrying(
        document_id=create_document_record.id,
        name=ProcessingStepName.OCR,
        error_type="TimeoutError",
        error_message="provider timeout again",
    )

    row = db_session.scalar(select(ProcessingStepORM))
    assert row is not None
    assert row.status == ProcessingStepStatus.RETRYING.value
    assert row.attempt_count == 2
    assert row.error_type == "TimeoutError"
    assert row.error_message == "provider timeout again"


def test_extracted_data_repository_create_empty_is_idempotent(
    db_session: Session,
    persisted_org_user: object,
    create_document_record: CreateDocumentRecord,
) -> None:
    DocumentRepository(db_session).create(create_document_record)
    repository = ExtractedDataRepository(db_session)

    repository.create_empty(create_document_record.id)
    repository.create_empty(create_document_record.id)
    db_session.flush()

    rows = db_session.scalars(select(ExtractedDataORM)).all()
    assert len(rows) == 1
    assert rows[0].document_id == create_document_record.id


def test_extracted_data_repository_clears_only_requested_outputs(
    db_session: Session,
    persisted_org_user: object,
    create_document_record: CreateDocumentRecord,
) -> None:
    DocumentRepository(db_session).create(create_document_record)
    row = ExtractedDataORM(
        document_id=create_document_record.id,
        ocr_text="raw text",
        metadata_json={"kind": "lease"},
        chunks_json=["chunk"],
        partner_result_json={"status": "ok"},
    )
    db_session.add(row)
    db_session.flush()

    ExtractedDataRepository(db_session).clear_outputs(create_document_record.id, ocr=True, chunks=True)

    assert row.ocr_text is None
    assert row.metadata_json == {"kind": "lease"}
    assert row.chunks_json is None
    assert row.partner_result_json == {"status": "ok"}


def test_extracted_data_repository_set_partner_result_persists_result(
    db_session: Session,
    persisted_org_user: object,
    create_document_record: CreateDocumentRecord,
) -> None:
    DocumentRepository(db_session).create(create_document_record)

    ExtractedDataRepository(db_session).set_partner_result(
        create_document_record.id,
        {"indexed_at": "2026-05-21T14:23:11Z"},
    )
    db_session.flush()

    row = db_session.get(ExtractedDataORM, create_document_record.id)
    assert row is not None
    assert row.partner_result_json == {"indexed_at": "2026-05-21T14:23:11Z"}
