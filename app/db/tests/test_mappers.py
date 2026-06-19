from app.db.models import DocumentORM, ProcessingStepORM
from app.domain.enums import DocumentStatus, ProcessingStepName, ProcessingStepStatus
from app.db.mappers import document_to_state, processing_step_to_state


def test_document_mapper_returns_domain_state(document_row: DocumentORM) -> None:
    state = document_to_state(document_row)

    assert state.id == document_row.id
    assert state.org_id == document_row.org_id
    assert state.status is DocumentStatus.WAITING_UPLOAD
    assert state.storage_key.endswith("/lease.pdf")


def test_processing_step_mapper_returns_domain_state(
    processing_step_row: ProcessingStepORM,
) -> None:
    state = processing_step_to_state(processing_step_row)

    assert state.id == processing_step_row.id
    assert state.document_id == processing_step_row.document_id
    assert state.name is ProcessingStepName.OCR
    assert state.status is ProcessingStepStatus.PENDING
