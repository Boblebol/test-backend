import pytest
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.seed import DEMO_PASSWORD, seed_demo_data

pytestmark = pytest.mark.integration


class FakeDevObjectStorage:
    def __init__(self) -> None:
        self.stored_objects: list[dict] = []

    def put_object(
        self,
        *,
        bucket: str,
        key: str,
        content: bytes,
        content_type: str,
    ) -> None:
        self.stored_objects.append(
            {
                "bucket": bucket,
                "key": key,
                "content": content,
                "content_type": content_type,
            }
        )


def test_dev_upload_endpoint_writes_file_to_document_storage_key(
    api_client,
    db_session: Session,
) -> None:
    seed_demo_data(db_session)
    storage = FakeDevObjectStorage()
    use_dev_storage(api_client, storage)
    headers = auth_headers(api_client, "alpha@example.com")
    document = create_document(api_client, headers)

    response = api_client.post(
        f"/dev/documents/{document['id']}/upload",
        headers=headers,
        files={"file": ("lease.pdf", b"%PDF-1.4\nfake\n%%EOF\n", "application/pdf")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "document_id": document["id"],
        "storage_bucket": "primmo-documents",
        "storage_key": document["storage_key"],
        "content_type": "application/pdf",
        "size_bytes": 20,
    }
    assert storage.stored_objects == [
        {
            "bucket": "primmo-documents",
            "key": document["storage_key"],
            "content": b"%PDF-1.4\nfake\n%%EOF\n",
            "content_type": "application/pdf",
        }
    ]


def test_dev_upload_endpoint_rejects_cross_tenant_access(api_client, db_session: Session) -> None:
    seed_demo_data(db_session)
    storage = FakeDevObjectStorage()
    use_dev_storage(api_client, storage)
    alpha_document = create_document(api_client, auth_headers(api_client, "alpha@example.com"))

    response = api_client.post(
        f"/dev/documents/{alpha_document['id']}/upload",
        headers=auth_headers(api_client, "beta@example.com"),
        files={"file": ("lease.pdf", b"%PDF-1.4\nfake\n%%EOF\n", "application/pdf")},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Document not found"}
    assert storage.stored_objects == []


def test_dev_upload_endpoint_is_disabled_outside_local_and_test(
    api_client,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_demo_data(db_session)
    storage = FakeDevObjectStorage()
    use_dev_storage(api_client, storage)
    headers = auth_headers(api_client, "alpha@example.com")
    document = create_document(api_client, headers)
    monkeypatch.setenv("APP_ENV", "prod")
    get_settings.cache_clear()

    try:
        response = api_client.post(
            f"/dev/documents/{document['id']}/upload",
            headers=headers,
            files={"file": ("lease.pdf", b"%PDF-1.4\nfake\n%%EOF\n", "application/pdf")},
        )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}
    assert storage.stored_objects == []


def use_dev_storage(api_client, storage: FakeDevObjectStorage) -> None:
    from app.modules.dev.routes import get_dev_object_storage

    api_client.app.dependency_overrides[get_dev_object_storage] = lambda: storage


def auth_headers(api_client, email: str) -> dict[str, str]:
    response = api_client.post(
        "/auth/login",
        json={"email": email, "password": DEMO_PASSWORD},
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def create_document(api_client, headers: dict[str, str]) -> dict:
    response = api_client.post(
        "/documents",
        json={
            "filename": "lease.pdf",
            "content_type": "application/pdf",
            "size_bytes": 20,
        },
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()
