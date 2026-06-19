import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import OrganizationORM, UserORM
from app.db.seed import DEMO_PASSWORD, seed_demo_data
from app.modules.auth.passwords import verify_password

pytestmark = pytest.mark.integration


def test_seed_demo_data_creates_two_orgs_and_two_users(db_session: Session) -> None:
    result = seed_demo_data(db_session)

    organizations = db_session.scalars(select(OrganizationORM).order_by(OrganizationORM.name)).all()
    users = db_session.scalars(select(UserORM).order_by(UserORM.email)).all()

    assert result.created_organizations == 2
    assert result.created_users == 2
    assert [organization.name for organization in organizations] == ["Primmo Alpha", "Primmo Beta"]
    assert [user.email for user in users] == ["alpha@example.com", "beta@example.com"]
    assert all(verify_password(DEMO_PASSWORD, user.password_hash) for user in users)


def test_seed_demo_data_is_idempotent(db_session: Session) -> None:
    seed_demo_data(db_session)
    result = seed_demo_data(db_session)

    organizations = db_session.scalars(select(OrganizationORM)).all()
    users = db_session.scalars(select(UserORM)).all()

    assert result.created_organizations == 0
    assert result.created_users == 0
    assert len(organizations) == 2
    assert len(users) == 2
