from uuid import uuid4

from app.domain.enums import DocumentStatus, ProcessingStepName, ProcessingStepStatus
from app.db.models import ProcessingStepORM
from app.domain.models import CreateDocumentCommand, ProcessingStepState, UserState


def test_document_status_values_match_public_contract() -> None:
    assert DocumentStatus.WAITING_UPLOAD == "waiting_upload"
    assert DocumentStatus.PROCESSING == "processing"
    assert DocumentStatus.WAITING_PARTNER == "waiting_partner"
    assert DocumentStatus.READY == "ready"
    assert DocumentStatus.FAILED == "failed"


def test_processing_step_enums_cover_pipeline() -> None:
    assert [step.value for step in ProcessingStepName] == [
        "ocr",
        "metadata",
        "chunking",
        "external_call",
        "partner_webhook",
    ]
    assert ProcessingStepStatus.WAITING_WEBHOOK == "waiting_webhook"


def test_processing_step_keeps_result_json_as_current_debug_payload() -> None:
    rich_execution_fields = {
        "celery_task_id",
        "started_at",
        "finished_at",
    }

    assert not rich_execution_fields.intersection(ProcessingStepState.__dataclass_fields__)
    assert not rich_execution_fields.intersection(ProcessingStepORM.__table__.columns)
    assert "result_json" in ProcessingStepState.__dataclass_fields__
    assert "result_json" in ProcessingStepORM.__table__.columns
    assert "created_at" in ProcessingStepORM.__table__.columns
    assert "updated_at" in ProcessingStepORM.__table__.columns


def test_user_model_is_only_org_scoped_without_roles() -> None:
    assert set(UserState.__dataclass_fields__) == {"id", "org_id", "email", "created_at"}


def test_create_document_command_keeps_tenant_context() -> None:
    org_id = uuid4()
    owner_user_id = uuid4()

    command = CreateDocumentCommand(
        org_id=org_id,
        org_name="Primmo Alpha",
        owner_user_id=owner_user_id,
        owner_user_email="alpha@example.com",
        filename="lease.pdf",
        content_type="application/pdf",
        size_bytes=1024,
    )

    assert command.org_id == org_id
    assert command.org_name == "Primmo Alpha"
    assert command.owner_user_id == owner_user_id
    assert command.owner_user_email == "alpha@example.com"
