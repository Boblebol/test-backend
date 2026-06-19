from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import OrganizationORM
from app.domain.models import OrganizationState
from app.db.mappers import organization_to_state


class OrganizationRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, org_id: UUID) -> OrganizationState | None:
        row = self.session.get(OrganizationORM, org_id)
        return organization_to_state(row) if row is not None else None

    def list(self) -> list[OrganizationState]:
        rows = self.session.scalars(select(OrganizationORM).order_by(OrganizationORM.name)).all()
        return [organization_to_state(row) for row in rows]
