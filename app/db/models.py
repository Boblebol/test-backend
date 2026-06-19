import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.domain.enums import (
    DocumentStatus,
    ProcessingStepStatus,
)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class OrganizationORM(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    users: Mapped[list["UserORM"]] = relationship(back_populates="organization")
    documents: Mapped[list["DocumentORM"]] = relationship(back_populates="organization")


class UserORM(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    organization: Mapped[OrganizationORM] = relationship(back_populates="users")
    documents: Mapped[list["DocumentORM"]] = relationship(back_populates="owner")


class DocumentORM(TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_org_created_id", "org_id", "created_at", "id"),
        Index("ix_documents_org_status", "org_id", "status"),
        Index(
            "ix_documents_external_job_id_unique",
            "external_job_id",
            unique=True,
            postgresql_where=text("external_job_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True, nullable=False)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    storage_bucket: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        default=DocumentStatus.WAITING_UPLOAD.value,
        index=True,
        nullable=False,
    )
    external_job_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    current_error_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    current_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    organization: Mapped[OrganizationORM] = relationship(back_populates="documents")
    owner: Mapped[UserORM] = relationship(back_populates="documents")
    steps: Mapped[list["ProcessingStepORM"]] = relationship(back_populates="document")
    extracted_data: Mapped["ExtractedDataORM | None"] = relationship(back_populates="document", uselist=False)


class ProcessingStepORM(TimestampMixin, Base):
    __tablename__ = "document_processing_steps"
    __table_args__ = (
        UniqueConstraint("document_id", "name", name="uq_document_processing_steps_document_name"),
        Index("ix_document_processing_steps_document_status", "document_id", "status"),
        Index("ix_document_processing_steps_name_status", "name", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        default=ProcessingStepStatus.PENDING.value,
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(default=0, nullable=False)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    document: Mapped[DocumentORM] = relationship(back_populates="steps")


class ExtractedDataORM(TimestampMixin, Base):
    __tablename__ = "document_extracted_data"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id"),
        primary_key=True,
    )
    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    chunks_json: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    partner_result_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    document: Mapped[DocumentORM] = relationship(back_populates="extracted_data")
