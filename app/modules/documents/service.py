import re
import unicodedata
import uuid
from collections.abc import Callable
from dataclasses import replace

from app.domain.enums import DocumentStatus
from app.domain.models import (
    CreateDocumentCommand,
    CreateDocumentRecord,
    DocumentState,
    UploadUrlState,
)


class InvalidDocumentUpload(ValueError):
    pass


class DocumentUploadNotPending(ValueError):
    pass


class UploadedFileMissing(ValueError):
    pass


class DocumentService:
    def __init__(
        self,
        *,
        documents,
        storage_bucket: str,
        max_upload_size_bytes: int | None = None,
        id_factory: Callable[[], uuid.UUID] = uuid.uuid4,
    ):
        self.documents = documents
        self.storage_bucket = storage_bucket
        self.max_upload_size_bytes = max_upload_size_bytes
        self.id_factory = id_factory

    def create_document(self, command: CreateDocumentCommand) -> DocumentState:
        self._validate_upload(command)
        document_id = self.id_factory()
        record = CreateDocumentRecord(
            id=document_id,
            org_id=command.org_id,
            owner_user_id=command.owner_user_id,
            original_filename=command.filename,
            content_type=command.content_type,
            size_bytes=command.size_bytes,
            storage_bucket=self.storage_bucket,
            storage_key=self._build_storage_key(
                org_name=command.org_name,
                owner_user_email=command.owner_user_email,
                filename=command.filename,
                document_id=document_id,
            ),
            status=DocumentStatus.WAITING_UPLOAD,
        )
        return self.documents.create(record)

    @staticmethod
    def _build_storage_key(
        *,
        org_name: str,
        owner_user_email: str,
        filename: str,
        document_id: uuid.UUID,
    ) -> str:
        org_slug = _storage_slug(org_name)
        user_slug = _storage_slug(owner_user_email)
        storage_filename = _storage_filename(filename)
        return f"orgs/{org_slug}/users/{user_slug}/documents/{document_id}/{storage_filename}"

    def _validate_upload(self, command: CreateDocumentCommand) -> None:
        if not command.filename.strip():
            raise InvalidDocumentUpload("filename is required")
        if command.content_type != "application/pdf":
            raise InvalidDocumentUpload("only application/pdf uploads are accepted")
        if command.size_bytes <= 0:
            raise InvalidDocumentUpload("size_bytes must be positive")
        if (
            self.max_upload_size_bytes is not None
            and command.size_bytes > self.max_upload_size_bytes
        ):
            raise InvalidDocumentUpload("file is too large")


class DocumentUploadService:
    def __init__(
        self,
        *,
        documents,
        storage,
        upload_url_expires_seconds: int,
    ):
        self.documents = documents
        self.storage = storage
        self.upload_url_expires_seconds = upload_url_expires_seconds

    def create_upload_url(self, document: DocumentState) -> UploadUrlState:
        self._ensure_waiting_upload(document)
        return UploadUrlState(
            document_id=document.id,
            upload_url=self.storage.create_upload_url(
                bucket=document.storage_bucket,
                key=document.storage_key,
                content_type=document.content_type,
                expires_seconds=self.upload_url_expires_seconds,
            ),
            upload_method="PUT",
            expires_in_seconds=self.upload_url_expires_seconds,
            upload_headers={"Content-Type": document.content_type},
        )

    def complete_upload(self, document: DocumentState) -> DocumentState:
        self._ensure_waiting_upload(document)
        if not self.storage.object_exists(
            bucket=document.storage_bucket,
            key=document.storage_key,
        ):
            raise UploadedFileMissing("Uploaded file not found")

        self.documents.update_status(document.id, DocumentStatus.UPLOADED)
        updated = self.documents.get(document.id)
        return updated if updated is not None else replace(document, status=DocumentStatus.UPLOADED)

    @staticmethod
    def _ensure_waiting_upload(document: DocumentState) -> None:
        if document.status is not DocumentStatus.WAITING_UPLOAD:
            raise DocumentUploadNotPending("Document is not waiting for upload")


def _storage_slug(value: str) -> str:
    ascii_value = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")
    return slug or "unknown"


def _storage_filename(filename: str) -> str:
    basename = filename.strip().replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    stem = basename[:-4] if basename.lower().endswith(".pdf") else basename
    return f"{_storage_slug(stem)}.pdf"
