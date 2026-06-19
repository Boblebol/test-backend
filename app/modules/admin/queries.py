from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import DocumentORM, OrganizationORM, ProcessingStepORM, UserORM


@dataclass(frozen=True)
class AdminOrganizationFilters:
    q: str = ""


@dataclass(frozen=True)
class AdminUserFilters:
    org_id: UUID | None = None
    q: str = ""


@dataclass(frozen=True)
class AdminDocumentFilters:
    org_id: UUID | None = None
    owner_user_id: UUID | None = None
    status: str = ""
    q: str = ""
    limit: int = 100


@dataclass(frozen=True)
class AdminProcessingStepFilters:
    org_id: UUID | None = None
    owner_user_id: UUID | None = None
    document_id: UUID | None = None
    document_status: str = ""
    step_name: str = ""
    step_status: str = ""
    q: str = ""
    limit: int = 100


@dataclass(frozen=True)
class AdminOrganizationRow:
    id: UUID
    name: str
    user_count: int
    document_count: int
    created_at: datetime | None


@dataclass(frozen=True)
class AdminUserRow:
    id: UUID
    org_id: UUID
    email: str
    organization_name: str
    document_count: int
    created_at: datetime | None


@dataclass(frozen=True)
class AdminDocumentRow:
    id: UUID
    org_id: UUID
    organization_name: str
    owner_user_id: UUID
    owner_email: str
    original_filename: str
    status: str
    external_job_id: str | None
    current_error_type: str | None
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(frozen=True)
class AdminCountRow:
    key: str
    count: int


@dataclass(frozen=True)
class AdminDashboardSnapshot:
    organization_count: int
    user_count: int
    document_count: int
    status_counts: list[AdminCountRow]
    step_status_counts: list[AdminCountRow]
    recent_documents: list[AdminDocumentRow]
    failed_documents: list[AdminDocumentRow]
    waiting_partner_documents: list[AdminDocumentRow]
    organizations: list[AdminOrganizationRow]


@dataclass(frozen=True)
class AdminDocumentDetail:
    document: AdminDocumentRow
    storage_key: str
    current_error_message: str | None
    updated_at: datetime | None
    steps: list["AdminProcessingStepRow"]


@dataclass(frozen=True)
class AdminProcessingStepRow:
    document_id: UUID
    document_filename: str
    document_status: str
    org_id: UUID
    organization_name: str
    owner_user_id: UUID
    owner_email: str
    name: str
    status: str
    attempt_count: int
    result_json: dict | None
    error_type: str | None
    error_message: str | None
    updated_by: str | None
    updated_at: datetime | None


class AdminQueries:
    def __init__(self, session: Session):
        self.session = session

    def dashboard(self, filters: AdminDocumentFilters) -> AdminDashboardSnapshot:
        return AdminDashboardSnapshot(
            organization_count=self.count_organizations(),
            user_count=self.count_users(org_id=filters.org_id),
            document_count=self.count_documents(filters),
            status_counts=self.count_documents_by_status(filters),
            step_status_counts=self.count_steps_by_status(filters),
            recent_documents=self.list_documents(filters),
            failed_documents=self.list_documents(
                AdminDocumentFilters(
                    org_id=filters.org_id,
                    owner_user_id=filters.owner_user_id,
                    status="failed",
                    q=filters.q,
                    limit=5,
                )
            ),
            waiting_partner_documents=self.list_documents(
                AdminDocumentFilters(
                    org_id=filters.org_id,
                    owner_user_id=filters.owner_user_id,
                    status="waiting_partner",
                    q=filters.q,
                    limit=10,
                )
            ),
            organizations=self.list_organizations(),
        )

    def list_organizations(
        self,
        filters: AdminOrganizationFilters | None = None,
    ) -> list[AdminOrganizationRow]:
        filters = filters or AdminOrganizationFilters()
        user_counts = self._counts_by_org(UserORM.org_id)
        document_counts = self._counts_by_org(DocumentORM.org_id)
        query = select(OrganizationORM)
        if filters.q:
            query = query.where(OrganizationORM.name.ilike(_like(filters.q)))
        organizations = self.session.scalars(query.order_by(OrganizationORM.name)).all()
        return [
            AdminOrganizationRow(
                id=organization.id,
                name=organization.name,
                user_count=user_counts.get(organization.id, 0),
                document_count=document_counts.get(organization.id, 0),
                created_at=organization.created_at,
            )
            for organization in organizations
        ]

    def list_users(self, filters: AdminUserFilters | None = None) -> list[AdminUserRow]:
        filters = filters or AdminUserFilters()
        document_counts = self._counts_by_user()
        query = (
            select(UserORM, OrganizationORM.name)
            .join(OrganizationORM, UserORM.org_id == OrganizationORM.id)
        )
        if filters.org_id is not None:
            query = query.where(UserORM.org_id == filters.org_id)
        if filters.q:
            pattern = _like(filters.q)
            query = query.where(
                or_(
                    UserORM.email.ilike(pattern),
                    OrganizationORM.name.ilike(pattern),
                )
            )
        rows = self.session.execute(query.order_by(OrganizationORM.name, UserORM.email)).all()
        return [
            AdminUserRow(
                id=user.id,
                org_id=user.org_id,
                email=user.email,
                organization_name=organization_name,
                document_count=document_counts.get(user.id, 0),
                created_at=user.created_at,
            )
            for user, organization_name in rows
        ]

    def list_documents(
        self,
        filters: AdminDocumentFilters | None = None,
    ) -> list[AdminDocumentRow]:
        filters = filters or AdminDocumentFilters()
        rows = self.session.execute(
            self._documents_query(filters)
            .order_by(DocumentORM.created_at.desc(), DocumentORM.id.desc())
            .limit(filters.limit)
        ).all()
        return [
            AdminDocumentRow(
                id=document.id,
                org_id=document.org_id,
                organization_name=organization_name,
                owner_user_id=document.owner_user_id,
                owner_email=owner_email,
                original_filename=document.original_filename,
                status=document.status,
                external_job_id=document.external_job_id,
                current_error_type=document.current_error_type,
                created_at=document.created_at,
                updated_at=document.updated_at,
            )
            for document, organization_name, owner_email in rows
        ]

    def count_organizations(self) -> int:
        return self.session.scalar(select(func.count()).select_from(OrganizationORM)) or 0

    def count_users(self, *, org_id: UUID | None = None) -> int:
        query = select(func.count()).select_from(UserORM)
        if org_id is not None:
            query = query.where(UserORM.org_id == org_id)
        return self.session.scalar(query) or 0

    def count_documents(self, filters: AdminDocumentFilters | None = None) -> int:
        filters = filters or AdminDocumentFilters()
        return self.session.scalar(self._document_filtered_count_query(filters)) or 0

    def count_documents_by_status(
        self,
        filters: AdminDocumentFilters | None = None,
    ) -> list[AdminCountRow]:
        filters = filters or AdminDocumentFilters()
        query = (
            self._document_filtered_select(select(DocumentORM.status, func.count()), filters)
            .group_by(DocumentORM.status)
            .order_by(DocumentORM.status)
        )
        return [AdminCountRow(key=status, count=count) for status, count in self.session.execute(query).all()]

    def count_steps_by_status(
        self,
        filters: AdminDocumentFilters | None = None,
    ) -> list[AdminCountRow]:
        filters = filters or AdminDocumentFilters()
        query = (
            select(ProcessingStepORM.status, func.count())
            .join(DocumentORM, ProcessingStepORM.document_id == DocumentORM.id)
            .join(OrganizationORM, DocumentORM.org_id == OrganizationORM.id)
            .join(UserORM, DocumentORM.owner_user_id == UserORM.id)
        )
        query = self._apply_document_filters(query, filters)
        query = query.group_by(ProcessingStepORM.status).order_by(ProcessingStepORM.status)
        return [AdminCountRow(key=status, count=count) for status, count in self.session.execute(query).all()]

    def list_processing_steps(
        self,
        filters: AdminProcessingStepFilters | None = None,
    ) -> list[AdminProcessingStepRow]:
        filters = filters or AdminProcessingStepFilters()
        rows = self.session.execute(
            self._processing_steps_query(filters)
            .order_by(ProcessingStepORM.updated_at.desc(), ProcessingStepORM.created_at.desc())
            .limit(filters.limit)
        ).all()
        return [
            AdminProcessingStepRow(
                document_id=document.id,
                document_filename=document.original_filename,
                document_status=document.status,
                org_id=document.org_id,
                organization_name=organization_name,
                owner_user_id=document.owner_user_id,
                owner_email=owner_email,
                name=step.name,
                status=step.status,
                attempt_count=step.attempt_count,
                result_json=step.result_json,
                error_type=step.error_type,
                error_message=step.error_message,
                updated_by=step.updated_by,
                updated_at=step.updated_at,
            )
            for step, document, organization_name, owner_email in rows
        ]

    def get_document_detail(self, document_id: UUID) -> AdminDocumentDetail | None:
        row = self.session.execute(
            select(DocumentORM, OrganizationORM.name, UserORM.email)
            .join(OrganizationORM, DocumentORM.org_id == OrganizationORM.id)
            .join(UserORM, DocumentORM.owner_user_id == UserORM.id)
            .where(DocumentORM.id == document_id)
        ).one_or_none()
        if row is None:
            return None

        document, organization_name, owner_email = row
        steps = self.session.scalars(
            select(ProcessingStepORM)
            .where(ProcessingStepORM.document_id == document.id)
            .order_by(ProcessingStepORM.created_at, ProcessingStepORM.name)
        ).all()
        return AdminDocumentDetail(
            document=AdminDocumentRow(
                id=document.id,
                org_id=document.org_id,
                organization_name=organization_name,
                owner_user_id=document.owner_user_id,
                owner_email=owner_email,
                original_filename=document.original_filename,
                status=document.status,
                external_job_id=document.external_job_id,
                current_error_type=document.current_error_type,
                created_at=document.created_at,
                updated_at=document.updated_at,
            ),
            storage_key=document.storage_key,
            current_error_message=document.current_error_message,
            updated_at=document.updated_at,
            steps=[
                AdminProcessingStepRow(
                    document_id=document.id,
                    document_filename=document.original_filename,
                    document_status=document.status,
                    org_id=document.org_id,
                    organization_name=organization_name,
                    owner_user_id=document.owner_user_id,
                    owner_email=owner_email,
                    name=step.name,
                    status=step.status,
                    attempt_count=step.attempt_count,
                    result_json=step.result_json,
                    error_type=step.error_type,
                    error_message=step.error_message,
                    updated_by=step.updated_by,
                    updated_at=step.updated_at,
                )
                for step in steps
            ],
        )

    def _processing_steps_query(self, filters: AdminProcessingStepFilters) -> Select:
        query = (
            select(ProcessingStepORM, DocumentORM, OrganizationORM.name, UserORM.email)
            .join(DocumentORM, ProcessingStepORM.document_id == DocumentORM.id)
            .join(OrganizationORM, DocumentORM.org_id == OrganizationORM.id)
            .join(UserORM, DocumentORM.owner_user_id == UserORM.id)
        )
        if filters.org_id is not None:
            query = query.where(DocumentORM.org_id == filters.org_id)
        if filters.owner_user_id is not None:
            query = query.where(DocumentORM.owner_user_id == filters.owner_user_id)
        if filters.document_id is not None:
            query = query.where(DocumentORM.id == filters.document_id)
        if filters.document_status:
            query = query.where(DocumentORM.status == filters.document_status)
        if filters.step_name:
            query = query.where(ProcessingStepORM.name == filters.step_name)
        if filters.step_status:
            query = query.where(ProcessingStepORM.status == filters.step_status)
        if filters.q:
            pattern = _like(filters.q)
            query = query.where(
                or_(
                    DocumentORM.original_filename.ilike(pattern),
                    DocumentORM.external_job_id.ilike(pattern),
                    DocumentORM.current_error_type.ilike(pattern),
                    ProcessingStepORM.error_type.ilike(pattern),
                    ProcessingStepORM.error_message.ilike(pattern),
                    OrganizationORM.name.ilike(pattern),
                    UserORM.email.ilike(pattern),
                )
            )
        return query

    def _documents_query(self, filters: AdminDocumentFilters) -> Select:
        return self._document_filtered_select(
            select(DocumentORM, OrganizationORM.name, UserORM.email),
            filters,
        )

    def _document_filtered_count_query(self, filters: AdminDocumentFilters) -> Select:
        return self._document_filtered_select(
            select(func.count()).select_from(DocumentORM),
            filters,
        )

    def _document_filtered_select(self, query: Select, filters: AdminDocumentFilters) -> Select:
        query = (
            query.join(OrganizationORM, DocumentORM.org_id == OrganizationORM.id)
            .join(UserORM, DocumentORM.owner_user_id == UserORM.id)
        )
        return self._apply_document_filters(query, filters)

    def _apply_document_filters(self, query: Select, filters: AdminDocumentFilters) -> Select:
        if filters.org_id is not None:
            query = query.where(DocumentORM.org_id == filters.org_id)
        if filters.owner_user_id is not None:
            query = query.where(DocumentORM.owner_user_id == filters.owner_user_id)
        if filters.status:
            query = query.where(DocumentORM.status == filters.status)
        if filters.q:
            pattern = _like(filters.q)
            query = query.where(
                or_(
                    DocumentORM.original_filename.ilike(pattern),
                    DocumentORM.external_job_id.ilike(pattern),
                    DocumentORM.current_error_type.ilike(pattern),
                    DocumentORM.current_error_message.ilike(pattern),
                    OrganizationORM.name.ilike(pattern),
                    UserORM.email.ilike(pattern),
                )
            )
        return query

    def _counts_by_org(self, org_column) -> dict[UUID, int]:
        rows = self.session.execute(
            select(org_column, func.count()).group_by(org_column)
        ).all()
        return {org_id: count for org_id, count in rows}

    def _counts_by_user(self) -> dict[UUID, int]:
        rows = self.session.execute(
            select(DocumentORM.owner_user_id, func.count()).group_by(DocumentORM.owner_user_id)
        ).all()
        return {user_id: count for user_id, count in rows}


def _like(value: str) -> str:
    return f"%{value.strip()}%"
