from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import UserORM
from app.domain.models import UserCredentialsState, UserState
from app.db.mappers import user_to_credentials_state, user_to_state


class UserRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, user_id: UUID) -> UserState | None:
        row = self.session.get(UserORM, user_id)
        return user_to_state(row) if row is not None else None

    def get_by_email(self, email: str) -> UserState | None:
        row = self.session.scalar(select(UserORM).where(UserORM.email == email))
        return user_to_state(row) if row is not None else None

    def get_credentials_by_email(self, email: str) -> UserCredentialsState | None:
        row = self.session.scalar(select(UserORM).where(UserORM.email == email))
        return user_to_credentials_state(row) if row is not None else None

    def list_for_org(self, org_id: UUID) -> list[UserState]:
        rows = self.session.scalars(
            select(UserORM).where(UserORM.org_id == org_id).order_by(UserORM.email)
        ).all()
        return [user_to_state(row) for row in rows]
