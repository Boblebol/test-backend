from app.db.models import (
    DocumentORM,
    ExtractedDataORM,
    OrganizationORM,
    ProcessingStepORM,
    UserORM,
)
from app.domain.enums import (
    DocumentStatus,
    ProcessingStepName,
    ProcessingStepStatus,
)
from app.domain.models import (
    DocumentState,
    ExtractedDataState,
    OrganizationState,
    ProcessingStepState,
    UserCredentialsState,
    UserState,
)


def organization_to_state(row: OrganizationORM) -> OrganizationState:
    return OrganizationState(id=row.id, name=row.name, created_at=row.created_at)


def user_to_state(row: UserORM) -> UserState:
    return UserState(
        id=row.id,
        org_id=row.org_id,
        email=row.email,
        created_at=row.created_at,
    )


def user_to_credentials_state(row: UserORM) -> UserCredentialsState:
    return UserCredentialsState(
        id=row.id,
        org_id=row.org_id,
        email=row.email,
        password_hash=row.password_hash,
        created_at=row.created_at,
    )


def document_to_state(row: DocumentORM) -> DocumentState:
    return DocumentState(
        id=row.id,
        org_id=row.org_id,
        owner_user_id=row.owner_user_id,
        original_filename=row.original_filename,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        storage_bucket=row.storage_bucket,
        storage_key=row.storage_key,
        status=DocumentStatus(row.status),
        external_job_id=row.external_job_id,
        current_error_type=row.current_error_type,
        current_error_message=row.current_error_message,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def processing_step_to_state(row: ProcessingStepORM) -> ProcessingStepState:
    return ProcessingStepState(
        id=row.id,
        document_id=row.document_id,
        name=ProcessingStepName(row.name),
        status=ProcessingStepStatus(row.status),
        attempt_count=row.attempt_count,
        result_json=row.result_json,
        error_type=row.error_type,
        error_message=row.error_message,
        updated_by=row.updated_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def extracted_data_to_state(row: ExtractedDataORM) -> ExtractedDataState:
    return ExtractedDataState(
        document_id=row.document_id,
        ocr_text=row.ocr_text,
        metadata_json=row.metadata_json,
        chunks_json=row.chunks_json,
        partner_result_json=row.partner_result_json,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
