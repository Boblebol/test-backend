from uuid import uuid4

import pytest

from app.domain.models import UserCredentialsState
from app.modules.auth.service import AuthService, InvalidCredentials
from app.modules.auth.passwords import hash_password


class UserRepositoryStub:
    def __init__(self, user: UserCredentialsState | None):
        self.user = user

    def get_credentials_by_email(self, email: str) -> UserCredentialsState | None:
        return self.user if self.user is not None and self.user.email == email else None


class TokenServiceStub:
    def create_access_token(self, *, user_id, org_id, email) -> str:
        return f"token-for:{user_id}:{org_id}:{email}"


def test_auth_service_returns_token_for_valid_credentials() -> None:
    user_id = uuid4()
    org_id = uuid4()
    service = AuthService(
        users=UserRepositoryStub(
            UserCredentialsState(
                id=user_id,
                org_id=org_id,
                email="alpha@example.com",
                password_hash=hash_password("primmo-demo"),
            )
        ),
        tokens=TokenServiceStub(),
    )

    result = service.login("alpha@example.com", "primmo-demo")

    assert result.token_type == "bearer"
    assert result.access_token == f"token-for:{user_id}:{org_id}:alpha@example.com"
    assert result.user.email == "alpha@example.com"


def test_auth_service_rejects_wrong_password() -> None:
    service = AuthService(
        users=UserRepositoryStub(
            UserCredentialsState(
                id=uuid4(),
                org_id=uuid4(),
                email="alpha@example.com",
                password_hash=hash_password("primmo-demo"),
            )
        ),
        tokens=TokenServiceStub(),
    )

    with pytest.raises(InvalidCredentials):
        service.login("alpha@example.com", "wrong-password")


def test_auth_service_rejects_unknown_email() -> None:
    service = AuthService(users=UserRepositoryStub(None), tokens=TokenServiceStub())

    with pytest.raises(InvalidCredentials):
        service.login("missing@example.com", "primmo-demo")
