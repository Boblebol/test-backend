from fastapi.testclient import TestClient

from app.main import create_app


def openapi_spec() -> dict:
    with TestClient(create_app()) as client:
        response = client.get("/openapi.json")
    assert response.status_code == 200
    return response.json()


def test_openapi_exposes_client_friendly_metadata_and_tags() -> None:
    spec = openapi_spec()
    assert spec["info"]["title"] == "Primmo Documents API"
    assert "Client flow" in spec["info"]["description"]
    assert [tag["name"] for tag in spec["tags"]] == [
        "Auth",
        "Documents",
        "Partner webhook",
        "Local test helpers",
        "Health",
    ]
    assert spec["tags"][1]["description"] == "Create, upload, process and read tenant documents."


def test_openapi_documents_routes_explain_the_happy_path() -> None:
    paths = openapi_spec()["paths"]
    assert paths["/documents"]["post"]["summary"] == "Create a document upload"
    assert "Use the returned upload_url" in paths["/documents"]["post"]["description"]
    assert paths["/documents"]["get"]["summary"] == "List tenant documents"
    assert "next_cursor" in paths["/documents"]["get"]["description"]
    assert paths["/documents/{document_id}/complete-upload"]["post"]["summary"] == (
        "Complete upload and start processing"
    )
    assert paths["/documents/{document_id}/result"]["get"]["summary"] == "Read extracted result"
    assert paths["/documents/{document_id}/events"]["get"]["summary"] == "Stream document progress"


def test_openapi_schemas_include_actionable_examples() -> None:
    schemas = openapi_spec()["components"]["schemas"]
    assert schemas["LoginRequest"]["example"] == {
        "email": "alpha@example.com",
        "password": "primmo-demo",
    }
    assert schemas["CreateDocumentRequest"]["example"] == {
        "filename": "lease.pdf",
        "content_type": "application/pdf",
        "size_bytes": 1024,
    }
    partner_request = openapi_spec()["paths"]["/webhooks/partner"]["post"]["requestBody"]
    assert (
        partner_request["content"]["application/json"]["example"]["job_id"]
        == "j_abc123def4567890"
    )
    webhook_parameters = openapi_spec()["paths"]["/webhooks/partner"]["post"]["parameters"]
    signature_header = next(
        parameter
        for parameter in webhook_parameters
        if parameter["name"] == "X-Partner-Signature"
    )
    assert "HMAC-SHA256" in signature_header["description"]
    assert schemas["PartnerSignatureRequest"]["example"]["body"].startswith('{"job_id"')
