from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DocumentORM, UserORM
from app.db.seed import DEMO_PASSWORD, seed_demo_data
from app.domain.enums import DocumentStatus, ProcessingStepName, ProcessingStepStatus
from app.modules.processing.step_repository import ProcessingStepRepository

pytestmark = pytest.mark.integration


class FakeObjectStorage:
    def __init__(self) -> None:
        self.existing_objects: set[tuple[str, str]] = set()
        self.upload_url_calls: list[tuple[str, str, str, int]] = []

    def create_upload_url(
        self,
        *,
        bucket: str,
        key: str,
        content_type: str,
        expires_seconds: int,
    ) -> str:
        self.upload_url_calls.append((bucket, key, content_type, expires_seconds))
        return f"http://storage.local/{bucket}/{key}"

    def object_exists(self, *, bucket: str, key: str) -> bool:
        return (bucket, key) in self.existing_objects


class FakePipelineOrchestrator:
    def __init__(self) -> None:
        self.enqueued_document_ids: list[str] = []

    def enqueue_full_pipeline(self, document_id) -> str:
        self.enqueued_document_ids.append(str(document_id))
        return "task-123"


def auth_headers(api_client, email: str) -> dict[str, str]:
    response = api_client.post(
        "/auth/login",
        json={"email": email, "password": DEMO_PASSWORD},
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def create_document(api_client, headers: dict[str, str], filename: str = "lease.pdf") -> dict:
    response = api_client.post(
        "/documents",
        json={
            "filename": filename,
            "content_type": "application/pdf",
            "size_bytes": 1024,
        },
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()


def use_storage(api_client, storage: FakeObjectStorage) -> None:
    from app.modules.documents.routes import get_object_storage

    api_client.app.dependency_overrides[get_object_storage] = lambda: storage


def use_pipeline(api_client, pipeline: FakePipelineOrchestrator) -> None:
    from app.modules.documents.routes import get_pipeline_orchestrator

    api_client.app.dependency_overrides[get_pipeline_orchestrator] = lambda: pipeline


def use_progress_subscriber(api_client, subscriber) -> None:
    from app.modules.documents.routes import get_progress_subscriber

    api_client.app.dependency_overrides[get_progress_subscriber] = lambda: subscriber


def test_create_document_uses_authenticated_user_context(api_client, db_session: Session) -> None:
    seed_demo_data(db_session)
    headers = auth_headers(api_client, "alpha@example.com")

    response = api_client.post(
        "/documents",
        json={
            "filename": "lease.pdf",
            "content_type": "application/pdf",
            "size_bytes": 1024,
        },
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["original_filename"] == "lease.pdf"
    assert body["content_type"] == "application/pdf"
    assert body["size_bytes"] == 1024
    assert body["status"] == "waiting_upload"
    assert body["storage_key"] == (
        f"orgs/primmo-alpha/users/alpha-example-com/documents/{body['id']}/lease.pdf"
    )
    assert "pipeline_version" not in body
    assert body["org_id"]
    assert body["owner_user_id"]


def test_create_document_returns_presigned_upload_url(api_client, db_session: Session) -> None:
    seed_demo_data(db_session)
    storage = FakeObjectStorage()
    use_storage(api_client, storage)

    response = api_client.post(
        "/documents",
        json={
            "filename": "lease.pdf",
            "content_type": "application/pdf",
            "size_bytes": 1024,
        },
        headers=auth_headers(api_client, "alpha@example.com"),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["document_id"] == body["id"]
    assert body["upload_method"] == "PUT"
    assert body["expires_in_seconds"] == 300
    assert body["upload_headers"] == {"Content-Type": "application/pdf"}
    assert body["upload_url"].startswith(
        "http://storage.local/primmo-documents/orgs/primmo-alpha/users/alpha-example-com/"
    )
    assert storage.upload_url_calls == [
        (
            "primmo-documents",
            body["storage_key"],
            "application/pdf",
            300,
        )
    ]


def test_list_documents_only_returns_current_org_documents(api_client, db_session: Session) -> None:
    seed_demo_data(db_session)
    alpha_headers = auth_headers(api_client, "alpha@example.com")
    beta_headers = auth_headers(api_client, "beta@example.com")
    alpha_document = create_document(api_client, alpha_headers, filename="alpha.pdf")
    beta_document = create_document(api_client, beta_headers, filename="beta.pdf")

    alpha_response = api_client.get("/documents", headers=alpha_headers)
    beta_response = api_client.get("/documents", headers=beta_headers)

    assert alpha_response.status_code == 200
    assert [document["id"] for document in alpha_response.json()["items"]] == [alpha_document["id"]]
    assert alpha_response.json()["next_cursor"] is None
    assert beta_response.status_code == 200
    assert [document["id"] for document in beta_response.json()["items"]] == [beta_document["id"]]
    assert beta_response.json()["next_cursor"] is None


def test_list_documents_filters_by_status(api_client, db_session: Session) -> None:
    seed_demo_data(db_session)
    headers = auth_headers(api_client, "alpha@example.com")
    waiting_document = create_document(api_client, headers, filename="waiting.pdf")
    uploaded_document = create_document(api_client, headers, filename="uploaded.pdf")
    uploaded_row = db_session.get(DocumentORM, UUID(uploaded_document["id"]))
    assert uploaded_row is not None
    uploaded_row.status = DocumentStatus.UPLOADED.value
    db_session.flush()

    response = api_client.get("/documents?status=uploaded", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert [document["id"] for document in body["items"]] == [uploaded_document["id"]]
    assert waiting_document["id"] not in [document["id"] for document in body["items"]]
    assert body["next_cursor"] is None


def test_list_documents_filters_by_owner_and_created_range(api_client, db_session: Session) -> None:
    seed_demo_data(db_session)
    headers = auth_headers(api_client, "alpha@example.com")
    alpha_user = db_session.scalar(select(UserORM).where(UserORM.email == "alpha@example.com"))
    assert alpha_user is not None
    teammate = UserORM(
        org_id=alpha_user.org_id,
        email="alpha-teammate@example.com",
        password_hash="hashed-password",
    )
    db_session.add(teammate)
    db_session.flush()
    older_document = create_document(api_client, headers, filename="older.pdf")
    matching_document = create_document(api_client, headers, filename="matching.pdf")
    other_owner_document = create_document(api_client, headers, filename="other-owner.pdf")
    base_time = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)
    updates = [
        (older_document, teammate.id, base_time - timedelta(days=1)),
        (matching_document, teammate.id, base_time),
        (other_owner_document, alpha_user.id, base_time),
    ]
    for document, owner_user_id, created_at in updates:
        row = db_session.get(DocumentORM, UUID(document["id"]))
        assert row is not None
        row.owner_user_id = owner_user_id
        row.created_at = created_at
        row.updated_at = created_at
    db_session.flush()

    response = api_client.get(
        "/documents",
        headers=headers,
        params={
            "owner_user_id": str(teammate.id),
            "created_from": base_time.isoformat(),
            "created_to": (base_time + timedelta(hours=1)).isoformat(),
        },
    )

    assert response.status_code == 200
    assert [document["id"] for document in response.json()["items"]] == [matching_document["id"]]


def test_list_documents_paginates_with_next_cursor(api_client, db_session: Session) -> None:
    seed_demo_data(db_session)
    headers = auth_headers(api_client, "alpha@example.com")
    oldest_document = create_document(api_client, headers, filename="oldest.pdf")
    middle_document = create_document(api_client, headers, filename="middle.pdf")
    newest_document = create_document(api_client, headers, filename="newest.pdf")
    base_time = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)
    for offset, document in enumerate([oldest_document, middle_document, newest_document]):
        row = db_session.get(DocumentORM, UUID(document["id"]))
        assert row is not None
        row.created_at = base_time + timedelta(minutes=offset)
        row.updated_at = base_time + timedelta(minutes=offset)
    db_session.flush()

    first_response = api_client.get("/documents?limit=2", headers=headers)

    assert first_response.status_code == 200
    first_body = first_response.json()
    assert [document["id"] for document in first_body["items"]] == [
        newest_document["id"],
        middle_document["id"],
    ]
    assert first_body["next_cursor"] is not None

    second_response = api_client.get(
        f"/documents?limit=2&cursor={first_body['next_cursor']}",
        headers=headers,
    )

    assert second_response.status_code == 200
    second_body = second_response.json()
    assert [document["id"] for document in second_body["items"]] == [oldest_document["id"]]
    assert second_body["next_cursor"] is None


def test_list_documents_rejects_invalid_cursor(api_client, db_session: Session) -> None:
    seed_demo_data(db_session)

    response = api_client.get(
        "/documents?cursor=not-a-valid-cursor",
        headers=auth_headers(api_client, "alpha@example.com"),
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid pagination cursor"}


def test_list_documents_openapi_includes_pagination_and_filter_parameters(api_client) -> None:
    response = api_client.get("/openapi.json")

    assert response.status_code == 200
    documents_get = response.json()["paths"]["/documents"]["get"]
    assert {parameter["name"] for parameter in documents_get["parameters"]} >= {
        "limit",
        "cursor",
        "status",
        "owner_user_id",
        "created_from",
        "created_to",
    }


def test_document_detail_rejects_cross_tenant_access(api_client, db_session: Session) -> None:
    seed_demo_data(db_session)
    alpha_document = create_document(api_client, auth_headers(api_client, "alpha@example.com"))

    response = api_client.get(
        f"/documents/{alpha_document['id']}",
        headers=auth_headers(api_client, "beta@example.com"),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Document not found"}


def test_document_detail_returns_current_pipeline_steps_for_failed_partner_webhook(
    api_client,
    db_session: Session,
) -> None:
    seed_demo_data(db_session)
    headers = auth_headers(api_client, "alpha@example.com")
    document = create_document(api_client, headers)
    document_id = UUID(document["id"])
    steps = ProcessingStepRepository(db_session)
    for name, step_status in {
        ProcessingStepName.OCR: ProcessingStepStatus.SUCCESS,
        ProcessingStepName.METADATA: ProcessingStepStatus.SUCCESS,
        ProcessingStepName.CHUNKING: ProcessingStepStatus.SUCCESS,
        ProcessingStepName.EXTERNAL_CALL: ProcessingStepStatus.SUCCESS,
        ProcessingStepName.PARTNER_WEBHOOK: ProcessingStepStatus.FAILED,
    }.items():
        steps.upsert(
            document_id=document_id,
            name=name,
            status=step_status,
            updated_by="test",
        )
    row = db_session.get(DocumentORM, document_id)
    assert row is not None
    row.status = DocumentStatus.FAILED.value
    row.current_error_type = "PartnerWebhookFailed"
    row.current_error_message = "partner returned status rejected"
    db_session.flush()

    response = api_client.get(f"/documents/{document_id}", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["current_error_type"] == "PartnerWebhookFailed"
    assert body["pipeline_steps"] == {
        "ocr": "success",
        "metadata": "success",
        "chunking": "success",
        "external_call": "success",
        "partner_webhook": "failed",
    }


def test_regenerate_upload_url_rejects_cross_tenant_access(api_client, db_session: Session) -> None:
    seed_demo_data(db_session)
    use_storage(api_client, FakeObjectStorage())
    alpha_document = create_document(api_client, auth_headers(api_client, "alpha@example.com"))

    response = api_client.get(
        f"/documents/{alpha_document['id']}/upload-url",
        headers=auth_headers(api_client, "beta@example.com"),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Document not found"}


def test_regenerate_upload_url_returns_url_for_waiting_document(
    api_client,
    db_session: Session,
) -> None:
    seed_demo_data(db_session)
    storage = FakeObjectStorage()
    use_storage(api_client, storage)
    headers = auth_headers(api_client, "alpha@example.com")
    document = create_document(api_client, headers)

    response = api_client.get(f"/documents/{document['id']}/upload-url", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "document_id": document["id"],
        "upload_url": f"http://storage.local/primmo-documents/{document['storage_key']}",
        "upload_method": "PUT",
        "expires_in_seconds": 300,
        "upload_headers": {"Content-Type": "application/pdf"},
    }


def test_complete_upload_marks_document_uploaded(api_client, db_session: Session) -> None:
    seed_demo_data(db_session)
    storage = FakeObjectStorage()
    pipeline = FakePipelineOrchestrator()
    use_storage(api_client, storage)
    use_pipeline(api_client, pipeline)
    headers = auth_headers(api_client, "alpha@example.com")
    document = create_document(api_client, headers)
    storage.existing_objects.add(("primmo-documents", document["storage_key"]))

    response = api_client.post(f"/documents/{document['id']}/complete-upload", headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == DocumentStatus.UPLOADED
    assert pipeline.enqueued_document_ids == [document["id"]]
    detail_response = api_client.get(f"/documents/{document['id']}", headers=headers)
    assert detail_response.json()["status"] == DocumentStatus.UPLOADED


def test_complete_upload_rejects_missing_object(api_client, db_session: Session) -> None:
    seed_demo_data(db_session)
    pipeline = FakePipelineOrchestrator()
    use_storage(api_client, FakeObjectStorage())
    use_pipeline(api_client, pipeline)
    headers = auth_headers(api_client, "alpha@example.com")
    document = create_document(api_client, headers)

    response = api_client.post(f"/documents/{document['id']}/complete-upload", headers=headers)

    assert response.status_code == 409
    assert response.json() == {"detail": "Uploaded file not found"}
    assert pipeline.enqueued_document_ids == []


def test_document_result_returns_conflict_until_document_is_ready(
    api_client,
    db_session: Session,
) -> None:
    seed_demo_data(db_session)
    headers = auth_headers(api_client, "alpha@example.com")
    document = create_document(api_client, headers)

    response = api_client.get(f"/documents/{document['id']}/result", headers=headers)

    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "message": "Document result is not ready",
            "document_id": document["id"],
            "status": "waiting_upload",
        }
    }


def test_document_result_openapi_documents_not_ready_response(api_client) -> None:
    response = api_client.get("/openapi.json")

    assert response.status_code == 200
    result_get = response.json()["paths"]["/documents/{document_id}/result"]["get"]
    assert result_get["responses"]["409"]["description"] == "Document result is not ready yet"


def test_create_document_rejects_non_pdf_upload(api_client, db_session: Session) -> None:
    seed_demo_data(db_session)

    response = api_client.post(
        "/documents",
        json={
            "filename": "lease.txt",
            "content_type": "text/plain",
            "size_bytes": 1024,
        },
        headers=auth_headers(api_client, "alpha@example.com"),
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "only application/pdf uploads are accepted"}


def test_create_document_rejects_too_large_upload(api_client, db_session: Session) -> None:
    seed_demo_data(db_session)

    response = api_client.post(
        "/documents",
        json={
            "filename": "lease.pdf",
            "content_type": "application/pdf",
            "size_bytes": 20 * 1024 * 1024 + 1,
        },
        headers=auth_headers(api_client, "alpha@example.com"),
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "file is too large"}


def test_document_events_streams_snapshot_and_progress_event(api_client, db_session: Session) -> None:
    seed_demo_data(db_session)
    headers = auth_headers(api_client, "alpha@example.com")
    document = create_document(api_client, headers)
    subscriber = FakeProgressSubscriber(
        [
            (
                '{"document_id":"%s","step":"ocr","step_status":"running",'
                '"document_status":"processing","occurred_at":"2026-06-15T12:00:00+00:00"}'
            )
            % document["id"]
        ]
    )
    use_progress_subscriber(api_client, subscriber)

    with api_client.stream("GET", f"/documents/{document['id']}/events", headers=headers) as response:
        body = response.read().decode()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert subscriber.subscribed_channel == f"document-progress:{document['org_id']}:{document['id']}"
    assert subscriber.closed is True
    assert "event: snapshot\n" in body
    assert f'"document_id":"{document["id"]}"' in body
    assert '"document_status":"waiting_upload"' in body
    assert "event: progress\n" in body
    assert '"step":"ocr"' in body
    assert '"step_status":"running"' in body


def test_document_events_rejects_cross_tenant_access(api_client, db_session: Session) -> None:
    seed_demo_data(db_session)
    alpha_document = create_document(api_client, auth_headers(api_client, "alpha@example.com"))
    subscriber = FakeProgressSubscriber([])
    use_progress_subscriber(api_client, subscriber)

    response = api_client.get(
        f"/documents/{alpha_document['id']}/events",
        headers=auth_headers(api_client, "beta@example.com"),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Document not found"}
    assert subscriber.subscribed_channel is None


def test_document_events_sends_keepalive_when_no_progress_message(api_client, db_session: Session) -> None:
    seed_demo_data(db_session)
    headers = auth_headers(api_client, "alpha@example.com")
    document = create_document(api_client, headers)
    subscriber = FakeProgressSubscriber([None])
    use_progress_subscriber(api_client, subscriber)

    with api_client.stream("GET", f"/documents/{document['id']}/events", headers=headers) as response:
        body = response.read().decode()

    assert response.status_code == 200
    assert ": keep-alive\n\n" in body


class FakeProgressSubscriber:
    def __init__(self, messages: list[str | None]) -> None:
        self.messages = messages
        self.subscribed_channel: str | None = None
        self.closed = False

    def subscribe(self, channel: str) -> None:
        self.subscribed_channel = channel

    def next_message(self, timeout_seconds: int) -> str | None:
        if not self.messages:
            raise StopIteration
        return self.messages.pop(0)

    def close(self) -> None:
        self.closed = True
