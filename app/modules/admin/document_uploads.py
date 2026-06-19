from dataclasses import dataclass, replace
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from werkzeug.datastructures import FileStorage

from app.core.config import Settings
from app.db.models import OrganizationORM, UserORM
from app.domain.models import CreateDocumentCommand
from app.modules.auth.passwords import hash_password
from app.modules.auth.repository import UserRepository
from app.modules.documents.repository import DocumentRepository
from app.modules.documents.service import (
    DocumentService,
    DocumentUploadService,
    InvalidDocumentUpload,
    UploadedFileMissing,
)
from app.modules.documents.storage import ObjectStorageUnavailable
from app.modules.organizations.repository import OrganizationRepository


LOAD_TEST_PASSWORD = "primmo-load-test"


@dataclass(frozen=True)
class AdminDocumentUploadResult:
    document_id: UUID | None
    filename: str
    owner_email: str
    status: str
    message: str
    storage_key: str | None = None
    task_id: str | None = None


class AdminDocumentUploadActions:
    def __init__(self, session: Session, *, storage, settings: Settings):
        self.session = session
        self.storage = storage
        self.documents = DocumentRepository(session)
        self.users = UserRepository(session)
        self.organizations = OrganizationRepository(session)
        self.document_service = DocumentService(
            documents=self.documents,
            storage_bucket=settings.minio_bucket,
            max_upload_size_bytes=settings.max_upload_size_bytes,
        )
        self.upload_service = DocumentUploadService(
            documents=self.documents,
            storage=storage,
            upload_url_expires_seconds=settings.upload_url_expires_seconds,
        )

    def create_uploaded_documents(
        self,
        *,
        owner_user_id: UUID,
        files: list[FileStorage],
    ) -> list[AdminDocumentUploadResult]:
        user = self.users.get(owner_user_id)
        if user is None:
            return [
                AdminDocumentUploadResult(
                    document_id=None,
                    filename=file.filename or "-",
                    owner_email="-",
                    status="failed",
                    message="Selected user was not found.",
                )
                for file in files
            ]
        organization = self.organizations.get(user.org_id)
        if organization is None:
            return [
                AdminDocumentUploadResult(
                    document_id=None,
                    filename=file.filename or "-",
                    owner_email=user.email,
                    status="failed",
                    message="Selected user organization was not found.",
                )
                for file in files
            ]

        return [
            self._create_uploaded_document(
                file=file,
                owner_user_id=user.id,
                owner_user_email=user.email,
                org_id=organization.id,
                org_name=organization.name,
            )
            for file in files
        ]

    def generate_fake_batch(
        self,
        *,
        organization_name: str,
        user_count: int,
        document_count: int,
        filename_prefix: str,
    ) -> list[AdminDocumentUploadResult]:
        organization = self._get_or_create_organization(organization_name)
        users = self._get_or_create_load_test_users(
            organization=organization,
            user_count=user_count,
        )
        filename_prefix = _clean_batch_prefix(filename_prefix)

        results: list[AdminDocumentUploadResult] = []
        for index in range(1, document_count + 1):
            user = users[(index - 1) % len(users)]
            filename = f"{filename_prefix}-{index:03d}.pdf"
            results.append(
                self._create_uploaded_document_from_content(
                    filename=filename,
                    content=_fake_pdf_content(
                        organization_name=organization.name,
                        owner_email=user.email,
                        filename=filename,
                        index=index,
                    ),
                    content_type="application/pdf",
                    owner_user_id=user.id,
                    owner_user_email=user.email,
                    org_id=organization.id,
                    org_name=organization.name,
                )
            )
        return results

    def generate_fake_documents_for_user(
        self,
        *,
        owner_user_id: UUID,
        document_count: int,
        filename_prefix: str,
    ) -> list[AdminDocumentUploadResult]:
        user = self.users.get(owner_user_id)
        if user is None:
            return [
                AdminDocumentUploadResult(
                    document_id=None,
                    filename="-",
                    owner_email="-",
                    status="failed",
                    message="Selected user was not found.",
                )
                for _ in range(document_count)
            ]
        organization = self.organizations.get(user.org_id)
        if organization is None:
            return [
                AdminDocumentUploadResult(
                    document_id=None,
                    filename="-",
                    owner_email=user.email,
                    status="failed",
                    message="Selected user organization was not found.",
                )
                for _ in range(document_count)
            ]

        filename_prefix = _clean_batch_prefix(filename_prefix)
        return [
            self._create_uploaded_document_from_content(
                filename=f"{filename_prefix}-{index:03d}.pdf",
                content=_fake_pdf_content(
                    organization_name=organization.name,
                    owner_email=user.email,
                    filename=f"{filename_prefix}-{index:03d}.pdf",
                    index=index,
                ),
                content_type="application/pdf",
                owner_user_id=user.id,
                owner_user_email=user.email,
                org_id=organization.id,
                org_name=organization.name,
            )
            for index in range(1, document_count + 1)
        ]

    @staticmethod
    def mark_queued(
        result: AdminDocumentUploadResult,
        *,
        task_id: str,
    ) -> AdminDocumentUploadResult:
        return replace(result, status="queued", message="Queued pipeline.", task_id=task_id)

    @staticmethod
    def mark_enqueue_failed(
        result: AdminDocumentUploadResult,
        *,
        error: Exception,
    ) -> AdminDocumentUploadResult:
        return replace(
            result,
            status="uploaded",
            message=f"Document uploaded, but pipeline enqueue failed: {type(error).__name__}",
        )

    def _create_uploaded_document(
        self,
        *,
        file: FileStorage,
        owner_user_id: UUID,
        owner_user_email: str,
        org_id: UUID,
        org_name: str,
    ) -> AdminDocumentUploadResult:
        filename = _clean_filename(file.filename)
        return self._create_uploaded_document_from_content(
            filename=filename,
            content=file.read(),
            content_type=_content_type(file),
            owner_user_id=owner_user_id,
            owner_user_email=owner_user_email,
            org_id=org_id,
            org_name=org_name,
        )

    def _create_uploaded_document_from_content(
        self,
        *,
        filename: str,
        content: bytes,
        content_type: str,
        owner_user_id: UUID,
        owner_user_email: str,
        org_id: UUID,
        org_name: str,
    ) -> AdminDocumentUploadResult:
        try:
            with self.session.begin_nested():
                document = self.document_service.create_document(
                    CreateDocumentCommand(
                        org_id=org_id,
                        org_name=org_name,
                        owner_user_id=owner_user_id,
                        owner_user_email=owner_user_email,
                        filename=filename,
                        content_type=content_type,
                        size_bytes=len(content),
                    )
                )
                self.storage.put_object(
                    bucket=document.storage_bucket,
                    key=document.storage_key,
                    content=content,
                    content_type=document.content_type,
                )
                uploaded = self.upload_service.complete_upload(document)
        except (
            InvalidDocumentUpload,
            ObjectStorageUnavailable,
            UploadedFileMissing,
        ) as exc:
            return AdminDocumentUploadResult(
                document_id=None,
                filename=filename or "-",
                owner_email=owner_user_email,
                status="failed",
                message=str(exc),
            )

        return AdminDocumentUploadResult(
            document_id=uploaded.id,
            filename=uploaded.original_filename,
            owner_email=owner_user_email,
            status="uploaded",
            message="Document uploaded.",
            storage_key=uploaded.storage_key,
        )

    def _get_or_create_organization(self, organization_name: str) -> OrganizationORM:
        cleaned_name = organization_name.strip()
        organization = self.session.scalar(
            select(OrganizationORM).where(OrganizationORM.name == cleaned_name)
        )
        if organization is None:
            organization = OrganizationORM(name=cleaned_name)
            self.session.add(organization)
            self.session.flush()
        return organization

    def _get_or_create_load_test_users(
        self,
        *,
        organization: OrganizationORM,
        user_count: int,
    ) -> list[UserORM]:
        email_prefix = _slug(organization.name)
        password_hash = hash_password(LOAD_TEST_PASSWORD)
        users: list[UserORM] = []
        for index in range(1, user_count + 1):
            email = f"{email_prefix}-user-{index:03d}@example.test"
            user = self.session.scalar(select(UserORM).where(UserORM.email == email))
            if user is None:
                user = UserORM(
                    org_id=organization.id,
                    email=email,
                    password_hash=password_hash,
                )
                self.session.add(user)
            users.append(user)
        self.session.flush()
        return users


def _clean_filename(raw_filename: str | None) -> str:
    if raw_filename is None:
        return ""
    return raw_filename.replace("\\", "/").rsplit("/", maxsplit=1)[-1]


def _content_type(file: FileStorage) -> str:
    if file.content_type:
        return file.content_type
    if (file.filename or "").lower().endswith(".pdf"):
        return "application/pdf"
    return "application/octet-stream"


def _clean_batch_prefix(raw_prefix: str) -> str:
    cleaned = raw_prefix.strip().replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    return cleaned.removesuffix(".pdf") or "fake-document"


def _fake_pdf_content(
    *,
    organization_name: str,
    owner_email: str,
    filename: str,
    index: int,
) -> bytes:
    text = _escape_pdf_text(
        f"Fake lease document {index} - {filename} - {organization_name} - {owner_email}"
    )
    return (
        "%PDF-1.4\n"
        "1 0 obj\n"
        "<< /Type /Catalog /Pages 2 0 R >>\n"
        "endobj\n"
        "2 0 obj\n"
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>\n"
        "endobj\n"
        "3 0 obj\n"
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\n"
        "endobj\n"
        "4 0 obj\n"
        f"<< /Length {len(text) + 35} >>\n"
        "stream\n"
        f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET\n"
        "endstream\n"
        "endobj\n"
        "5 0 obj\n"
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\n"
        "endobj\n"
        "trailer\n"
        "<< /Root 1 0 R >>\n"
        "%%EOF\n"
    ).encode()


def _escape_pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _slug(value: str) -> str:
    slug = "".join(character.lower() if character.isalnum() else "-" for character in value)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "load-test"
