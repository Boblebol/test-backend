from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.db.models import DocumentORM
from app.domain.enums import DocumentStatus
from app.domain.models import CreateDocumentRecord, DocumentState
from app.db.mappers import document_to_state


class DocumentRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, record: CreateDocumentRecord) -> DocumentState:
        row = DocumentORM(
            id=record.id,
            org_id=record.org_id,
            owner_user_id=record.owner_user_id,
            original_filename=record.original_filename,
            content_type=record.content_type,
            size_bytes=record.size_bytes,
            storage_bucket=record.storage_bucket,
            storage_key=record.storage_key,
            status=record.status.value,
        )
        self.session.add(row)
        self.session.flush()
        return document_to_state(row)

    def get(self, document_id: UUID) -> DocumentState | None:
        row = self.session.get(DocumentORM, document_id)
        return document_to_state(row) if row is not None else None

    def get_for_org(self, document_id: UUID, org_id: UUID) -> DocumentState | None:
        row = self.session.scalar(
            select(DocumentORM).where(
                DocumentORM.id == document_id,
                DocumentORM.org_id == org_id,
            )
        )
        return document_to_state(row) if row is not None else None

    def get_by_external_job_id(self, external_job_id: str) -> DocumentState | None:
        row = self.session.scalar(
            select(DocumentORM).where(DocumentORM.external_job_id == external_job_id)
        )
        return document_to_state(row) if row is not None else None

    def list_for_org(self, org_id: UUID, limit: int = 50) -> list[DocumentState]:
        rows = self.session.scalars(
            select(DocumentORM)
            .where(DocumentORM.org_id == org_id)
            .order_by(DocumentORM.created_at.desc(), DocumentORM.id.desc())
            .limit(limit)
        ).all()
        return [document_to_state(row) for row in rows]

    def list_for_org_page(
        self,
        *,
        org_id: UUID,
        limit: int,
        status: DocumentStatus | None = None,
        owner_user_id: UUID | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        cursor: tuple[datetime, UUID] | None = None,
    ) -> list[DocumentState]:
        query = select(DocumentORM).where(DocumentORM.org_id == org_id)
        if status is not None:
            query = query.where(DocumentORM.status == status.value)
        if owner_user_id is not None:
            query = query.where(DocumentORM.owner_user_id == owner_user_id)
        if created_from is not None:
            query = query.where(DocumentORM.created_at >= created_from)
        if created_to is not None:
            query = query.where(DocumentORM.created_at <= created_to)
        if cursor is not None:
            cursor_created_at, cursor_id = cursor
            query = query.where(
                or_(
                    DocumentORM.created_at < cursor_created_at,
                    and_(
                        DocumentORM.created_at == cursor_created_at,
                        DocumentORM.id < cursor_id,
                    ),
                )
            )

        rows = self.session.scalars(
            query.order_by(DocumentORM.created_at.desc(), DocumentORM.id.desc()).limit(limit)
        ).all()
        return [document_to_state(row) for row in rows]

    def list_stale_uploaded(self, *, cutoff: datetime, limit: int) -> list[DocumentState]:
        rows = self.session.scalars(
            select(DocumentORM)
            .where(
                DocumentORM.status == DocumentStatus.UPLOADED.value,
                DocumentORM.updated_at < cutoff,
            )
            .order_by(DocumentORM.updated_at.asc(), DocumentORM.id.asc())
            .limit(limit)
        ).all()
        return [document_to_state(row) for row in rows]

    def update_status(self, document_id: UUID, status: DocumentStatus) -> None:
        row = self.session.get(DocumentORM, document_id)
        if row is None:
            return
        row.status = status.value
        if status is not DocumentStatus.FAILED:
            row.current_error_type = None
            row.current_error_message = None

    def mark_failed(self, document_id: UUID, error_type: str, error_message: str) -> None:
        row = self.session.get(DocumentORM, document_id)
        if row is None:
            return
        row.status = DocumentStatus.FAILED.value
        row.current_error_type = error_type
        row.current_error_message = error_message

    def clear_external_job(self, document_id: UUID) -> None:
        row = self.session.get(DocumentORM, document_id)
        if row is not None:
            row.external_job_id = None

    def set_external_job(self, document_id: UUID, job_id: str) -> None:
        row = self.session.get(DocumentORM, document_id)
        if row is not None:
            row.external_job_id = job_id
            row.status = DocumentStatus.WAITING_PARTNER.value
