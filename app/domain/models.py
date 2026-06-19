from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from app.domain.enums import (
    DocumentStatus,
    ProcessingStepName,
    ProcessingStepStatus,
)


@dataclass(frozen=True)
class CreateDocumentCommand:
    org_id: UUID
    org_name: str
    owner_user_id: UUID
    owner_user_email: str
    filename: str
    content_type: str
    size_bytes: int


@dataclass(frozen=True)
class CreateDocumentRecord:
    id: UUID
    org_id: UUID
    owner_user_id: UUID
    original_filename: str
    content_type: str
    size_bytes: int
    storage_bucket: str
    storage_key: str
    status: DocumentStatus


@dataclass(frozen=True)
class OrganizationState:
    id: UUID
    name: str
    created_at: datetime | None = None


@dataclass(frozen=True)
class UserState:
    id: UUID
    org_id: UUID
    email: str
    created_at: datetime | None = None


@dataclass(frozen=True)
class UserCredentialsState:
    id: UUID
    org_id: UUID
    email: str
    password_hash: str
    created_at: datetime | None = None


@dataclass(frozen=True)
class LoginResult:
    access_token: str
    token_type: str
    user: UserState


@dataclass(frozen=True)
class UploadUrlState:
    document_id: UUID
    upload_url: str
    upload_method: str
    expires_in_seconds: int
    upload_headers: dict[str, str]


@dataclass(frozen=True)
class DocumentState:
    id: UUID
    org_id: UUID
    owner_user_id: UUID
    original_filename: str
    content_type: str
    size_bytes: int
    storage_bucket: str
    storage_key: str
    status: DocumentStatus
    external_job_id: str | None
    current_error_type: str | None
    current_error_message: str | None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class ProcessingStepState:
    id: UUID
    document_id: UUID
    name: ProcessingStepName
    status: ProcessingStepStatus
    attempt_count: int
    result_json: dict[str, Any] | None
    error_type: str | None
    error_message: str | None
    updated_by: str | None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class ExtractedDataState:
    document_id: UUID
    ocr_text: str | None
    metadata_json: dict[str, Any] | None
    chunks_json: list[str] | None
    partner_result_json: dict[str, Any] | None
    created_at: datetime | None = None
    updated_at: datetime | None = None
