from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.modules.auth.tokens import TokenPayload, TokenService, TokenValidationError


def test_token_service_round_trips_user_claims() -> None:
    user_id = uuid4()
    org_id = uuid4()
    service = TokenService(secret="test-secret-with-at-least-32-bytes", expires_minutes=30)

    token = service.create_access_token(
        user_id=user_id,
        org_id=org_id,
        email="alpha@example.com",
        now=datetime.now(UTC),
    )

    payload = service.decode_access_token(token)

    assert payload == TokenPayload(
        user_id=user_id,
        org_id=org_id,
        email="alpha@example.com",
    )


def test_token_service_rejects_expired_tokens() -> None:
    service = TokenService(secret="test-secret-with-at-least-32-bytes", expires_minutes=30)
    token = service.create_access_token(
        user_id=uuid4(),
        org_id=uuid4(),
        email="alpha@example.com",
        now=datetime.now(UTC) - timedelta(hours=1),
    )

    with pytest.raises(TokenValidationError):
        service.decode_access_token(token)
