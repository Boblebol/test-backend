from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from app.modules.auth.repository import UserRepository


pytestmark = pytest.mark.integration


def test_user_repository_get_by_email_returns_org_scoped_user(
    db_session: Session,
    persisted_org_user: object,
    org_id: UUID,
    owner_user_id: UUID,
) -> None:
    state = UserRepository(db_session).get_by_email(f"{owner_user_id.hex}@example.com")

    assert state is not None
    assert state.id == owner_user_id
    assert state.org_id == org_id
    assert state.email == f"{owner_user_id.hex}@example.com"


def test_user_repository_get_credentials_by_email_includes_password_hash(
    db_session: Session,
    persisted_org_user: object,
    owner_user_id: UUID,
) -> None:
    state = UserRepository(db_session).get_credentials_by_email(f"{owner_user_id.hex}@example.com")

    assert state is not None
    assert state.id == owner_user_id
    assert state.email == f"{owner_user_id.hex}@example.com"
    assert state.password_hash == "hashed-password"
