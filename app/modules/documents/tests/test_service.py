from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest

from app.domain.enums import DocumentStatus
from app.domain.models import CreateDocumentCommand, CreateDocumentRecord, DocumentState
from app.modules.documents.service import (
    DocumentService,
    DocumentUploadNotPending,
    DocumentUploadService,
    InvalidDocumentUpload,
    UploadedFileMissing,
)


def test_document_service_creates_waiting_upload_document(
    document_id: UUID,
    org_id: UUID,
    create_document_command: CreateDocumentCommand,
    document_state: DocumentState,
    document_repository: Mock,
) -> None:
    document_repository.create.return_value = document_state
    service = DocumentService(
        documents=document_repository,
        storage_bucket="primmo-documents",
        id_factory=lambda: document_id,
    )

    state = service.create_document(create_document_command)

    assert state.status is DocumentStatus.WAITING_UPLOAD
    document_repository.create.assert_called_once()
    record = document_repository.create.call_args.args[0]
    assert isinstance(record, CreateDocumentRecord)
    assert record.id == document_id
    assert record.org_id == org_id
    assert record.storage_key == (
        f"orgs/org-{org_id.hex[:8]}/users/user-{create_document_command.owner_user_id.hex[:8]}-example-com/"
        f"documents/{document_id}/lease.pdf"
    )


def test_document_service_uses_sanitized_original_filename_in_storage_key(
    document_id: UUID,
    org_id: UUID,
    owner_user_id: UUID,
    document_repository: Mock,
) -> None:
    service = DocumentService(
        documents=document_repository,
        storage_bucket="primmo-documents",
        id_factory=lambda: document_id,
    )

    service.create_document(
        CreateDocumentCommand(
            org_id=org_id,
            org_name="Primmo Alpha",
            owner_user_id=owner_user_id,
            owner_user_email="alpha@example.com",
            filename="Bail signé 2026.PDF",
            content_type="application/pdf",
            size_bytes=1024,
        )
    )

    record = document_repository.create.call_args.args[0]
    assert record.storage_key == (
        f"orgs/primmo-alpha/users/alpha-example-com/documents/{document_id}/bail-signe-2026.pdf"
    )


def test_document_service_rejects_non_pdf_upload(document_repository: Mock) -> None:
    service = DocumentService(
        documents=document_repository,
        storage_bucket="primmo-documents",
        id_factory=uuid4,
    )

    with pytest.raises(InvalidDocumentUpload):
        service.create_document(
            CreateDocumentCommand(
                org_id=uuid4(),
                org_name="Primmo Alpha",
                owner_user_id=uuid4(),
                owner_user_email="alpha@example.com",
                filename="lease.txt",
                content_type="text/plain",
                size_bytes=10,
            )
        )
    document_repository.create.assert_not_called()


def test_document_service_rejects_too_large_upload(document_repository: Mock) -> None:
    service = DocumentService(
        documents=document_repository,
        storage_bucket="primmo-documents",
        max_upload_size_bytes=100,
        id_factory=uuid4,
    )

    with pytest.raises(InvalidDocumentUpload, match="file is too large"):
        service.create_document(
            CreateDocumentCommand(
                org_id=uuid4(),
                org_name="Primmo Alpha",
                owner_user_id=uuid4(),
                owner_user_email="alpha@example.com",
                filename="lease.pdf",
                content_type="application/pdf",
                size_bytes=101,
            )
        )
    document_repository.create.assert_not_called()


def test_document_upload_service_generates_upload_url(
    document_state: DocumentState,
    document_repository: Mock,
) -> None:
    storage = Mock(name="ObjectStorage")
    storage.create_upload_url.return_value = "http://storage.local/upload"
    service = DocumentUploadService(
        documents=document_repository,
        storage=storage,
        upload_url_expires_seconds=300,
    )

    upload = service.create_upload_url(document_state)

    assert upload.document_id == document_state.id
    assert upload.upload_url == "http://storage.local/upload"
    assert upload.upload_method == "PUT"
    assert upload.expires_in_seconds == 300
    assert upload.upload_headers == {"Content-Type": "application/pdf"}
    storage.create_upload_url.assert_called_once_with(
        bucket=document_state.storage_bucket,
        key=document_state.storage_key,
        content_type=document_state.content_type,
        expires_seconds=300,
    )


def test_document_upload_service_rejects_non_waiting_upload_document(
    document_state: DocumentState,
    document_repository: Mock,
) -> None:
    uploaded_document = DocumentState(
        **{
            **document_state.__dict__,
            "status": DocumentStatus.UPLOADED,
        }
    )
    storage = Mock(name="ObjectStorage")
    service = DocumentUploadService(
        documents=document_repository,
        storage=storage,
        upload_url_expires_seconds=300,
    )

    with pytest.raises(DocumentUploadNotPending):
        service.create_upload_url(uploaded_document)
    storage.create_upload_url.assert_not_called()


def test_document_upload_service_completes_existing_upload(
    document_state: DocumentState,
    document_repository: Mock,
) -> None:
    storage = Mock(name="ObjectStorage")
    storage.object_exists.return_value = True
    document_repository.get.return_value = DocumentState(
        **{
            **document_state.__dict__,
            "status": DocumentStatus.UPLOADED,
        }
    )
    service = DocumentUploadService(
        documents=document_repository,
        storage=storage,
        upload_url_expires_seconds=300,
    )

    updated = service.complete_upload(document_state)

    assert updated.status is DocumentStatus.UPLOADED
    storage.object_exists.assert_called_once_with(
        bucket=document_state.storage_bucket,
        key=document_state.storage_key,
    )
    document_repository.update_status.assert_called_once_with(
        document_state.id,
        DocumentStatus.UPLOADED,
    )


def test_document_upload_service_rejects_missing_upload(
    document_state: DocumentState,
    document_repository: Mock,
) -> None:
    storage = Mock(name="ObjectStorage")
    storage.object_exists.return_value = False
    service = DocumentUploadService(
        documents=document_repository,
        storage=storage,
        upload_url_expires_seconds=300,
    )

    with pytest.raises(UploadedFileMissing):
        service.complete_upload(document_state)
    document_repository.update_status.assert_not_called()
