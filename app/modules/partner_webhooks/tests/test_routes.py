import hashlib
import hmac
import json
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.db.seed import seed_demo_data
from app.domain.enums import DocumentStatus, ProcessingStepName, ProcessingStepStatus
from app.domain.models import CreateDocumentRecord
from app.modules.documents.repository import DocumentRepository
from app.modules.organizations.repository import OrganizationRepository
from app.modules.processing.result_repository import ExtractedDataRepository
from app.modules.processing.step_repository import ProcessingStepRepository
from app.modules.auth.repository import UserRepository
from app.modules.processing.service import ProcessingService

pytestmark = pytest.mark.integration

PARTNER_SECRET = "local-partner-secret-change-me"


@pytest.fixture(autouse=True)
def disable_redis_progress_publish(api_client) -> None:
    from app.modules.partner_webhooks.routes import get_progress_publisher
    from app.modules.processing.progress import NullProgressPublisher

    api_client.app.dependency_overrides[get_progress_publisher] = lambda: NullProgressPublisher()


def test_partner_webhook_completed_marks_document_ready_and_stores_result(
    api_client,
    db_session: Session,
) -> None:
    document = create_waiting_partner_document(db_session, job_id="j_completed")
    raw_body = webhook_body(
        job_id="j_completed",
        status="completed",
        result={"indexed_at": "2026-05-21T14:23:11Z"},
    )

    response = api_client.post(
        "/webhooks/partner",
        content=raw_body,
        headers=signed_headers(raw_body),
    )

    assert response.status_code == 200
    assert response.json() == {"document_id": str(document.id), "status": "ready"}
    updated_document = DocumentRepository(db_session).get(document.id)
    assert updated_document is not None
    assert updated_document.status is DocumentStatus.READY
    extracted = ExtractedDataRepository(db_session).get(document.id)
    assert extracted is not None
    assert extracted.partner_result_json == {"indexed_at": "2026-05-21T14:23:11Z"}
    assert step_status(db_session, document.id, ProcessingStepName.PARTNER_WEBHOOK) is ProcessingStepStatus.SUCCESS


def test_partner_webhook_failed_status_marks_document_failed(
    api_client,
    db_session: Session,
) -> None:
    document = create_waiting_partner_document(db_session, job_id="j_failed")
    raw_body = webhook_body(
        job_id="j_failed",
        status="rejected",
        result={"reason": "compliance rejected"},
    )

    response = api_client.post(
        "/webhooks/partner",
        content=raw_body,
        headers=signed_headers(raw_body),
    )

    assert response.status_code == 200
    assert response.json() == {"document_id": str(document.id), "status": "failed"}
    updated_document = DocumentRepository(db_session).get(document.id)
    assert updated_document is not None
    assert updated_document.status is DocumentStatus.FAILED
    assert updated_document.current_error_type == "PartnerWebhookFailed"
    assert updated_document.current_error_message == "partner returned status rejected"
    assert step_status(db_session, document.id, ProcessingStepName.PARTNER_WEBHOOK) is ProcessingStepStatus.FAILED


def test_partner_webhook_rejects_invalid_signature(api_client, db_session: Session) -> None:
    document = create_waiting_partner_document(db_session, job_id="j_bad_signature")
    raw_body = webhook_body(job_id="j_bad_signature", status="completed", result={})

    response = api_client.post(
        "/webhooks/partner",
        content=raw_body,
        headers={"content-type": "application/json", "x-partner-signature": "bad-signature"},
    )

    assert response.status_code == 401
    updated_document = DocumentRepository(db_session).get(document.id)
    assert updated_document is not None
    assert updated_document.status is DocumentStatus.WAITING_PARTNER


def test_partner_webhook_returns_404_for_unknown_job(api_client) -> None:
    raw_body = webhook_body(job_id="j_unknown", status="completed", result={})

    response = api_client.post(
        "/webhooks/partner",
        content=raw_body,
        headers=signed_headers(raw_body),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Partner job not found"}


def test_partner_webhook_is_idempotent_when_document_is_already_ready(
    api_client,
    db_session: Session,
) -> None:
    document = create_waiting_partner_document(db_session, job_id="j_duplicate")
    first_body = webhook_body(
        job_id="j_duplicate",
        status="completed",
        result={"indexed_at": "first"},
    )
    second_body = webhook_body(
        job_id="j_duplicate",
        status="completed",
        result={"indexed_at": "second"},
    )

    first_response = api_client.post(
        "/webhooks/partner",
        content=first_body,
        headers=signed_headers(first_body),
    )
    second_response = api_client.post(
        "/webhooks/partner",
        content=second_body,
        headers=signed_headers(second_body),
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    extracted = ExtractedDataRepository(db_session).get(document.id)
    assert extracted is not None
    assert extracted.partner_result_json == {"indexed_at": "first"}


def test_dev_partner_signature_endpoint_returns_valid_signature(api_client) -> None:
    raw_body = '{"job_id":"j_123","status":"completed"}'

    response = api_client.post("/dev/partner-signature", json={"body": raw_body})

    assert response.status_code == 200
    assert response.json() == {
        "signature": hmac.new(
            PARTNER_SECRET.encode(),
            raw_body.encode(),
            hashlib.sha256,
        ).hexdigest()
    }


def create_waiting_partner_document(db_session: Session, job_id: str):
    seed_demo_data(db_session)
    user = UserRepository(db_session).get_by_email("alpha@example.com")
    assert user is not None
    organization = OrganizationRepository(db_session).get(user.org_id)
    assert organization is not None
    document_id = uuid4()
    document = DocumentRepository(db_session).create(
        CreateDocumentRecord(
            id=document_id,
            org_id=user.org_id,
            owner_user_id=user.id,
            original_filename="lease.pdf",
            content_type="application/pdf",
            size_bytes=1024,
            storage_bucket="primmo-documents",
            storage_key=(
                f"orgs/{organization.name.lower().replace(' ', '-')}/"
                f"users/alpha-example-com/documents/{document_id}/lease.pdf"
            ),
            status=DocumentStatus.UPLOADED,
        )
    )
    service = ProcessingService(
        documents=DocumentRepository(db_session),
        steps=ProcessingStepRepository(db_session),
        extracted_data=ExtractedDataRepository(db_session),
    )
    service.initialize_pipeline(document.id, updated_by="test")
    service.mark_waiting_partner(document.id, job_id)
    db_session.flush()
    return document


def webhook_body(job_id: str, status: str, result: dict) -> bytes:
    return json.dumps(
        {
            "job_id": job_id,
            "status": status,
            "result": result,
            "occurred_at": "2026-05-21T14:23:11Z",
        },
        separators=(",", ":"),
    ).encode()


def signed_headers(raw_body: bytes) -> dict[str, str]:
    return {
        "content-type": "application/json",
        "x-partner-signature": hmac.new(PARTNER_SECRET.encode(), raw_body, hashlib.sha256).hexdigest(),
    }


def step_status(db_session: Session, document_id, name: ProcessingStepName) -> ProcessingStepStatus:
    step = next(
        step
        for step in ProcessingStepRepository(db_session).list_for_document(document_id)
        if step.name is name
    )
    return step.status
