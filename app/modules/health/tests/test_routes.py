import pytest

pytestmark = pytest.mark.integration


def test_health_endpoint_returns_ok(api_client) -> None:
    response = api_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_endpoint_exposes_health_route(api_client) -> None:
    response = api_client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["paths"]["/health"]["get"]["tags"] == ["Health"]
