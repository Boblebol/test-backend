import pytest
from sqlalchemy.orm import Session

from app.db.seed import DEMO_PASSWORD, seed_demo_data

pytestmark = pytest.mark.integration


def test_login_returns_bearer_token(api_client, db_session: Session) -> None:
    seed_demo_data(db_session)

    response = api_client.post(
        "/auth/login",
        json={"email": "alpha@example.com", "password": DEMO_PASSWORD},
    )

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["access_token"]


def test_me_returns_authenticated_user(api_client, db_session: Session) -> None:
    seed_demo_data(db_session)
    login_response = api_client.post(
        "/auth/login",
        json={"email": "alpha@example.com", "password": DEMO_PASSWORD},
    )

    response = api_client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {login_response.json()['access_token']}"},
    )

    assert response.status_code == 200
    assert response.json()["email"] == "alpha@example.com"
    assert response.json()["org_id"]


def test_login_rejects_wrong_password(api_client, db_session: Session) -> None:
    seed_demo_data(db_session)

    response = api_client.post(
        "/auth/login",
        json={"email": "alpha@example.com", "password": "wrong-password"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid email or password"}


def test_me_requires_bearer_token(api_client) -> None:
    response = api_client.get("/auth/me")

    assert response.status_code == 401
