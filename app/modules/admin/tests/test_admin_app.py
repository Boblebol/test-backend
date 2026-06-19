from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO
from uuid import UUID
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import DocumentORM, ExtractedDataORM, OrganizationORM, ProcessingStepORM, UserORM
from app.db.seed import seed_demo_data
from app.domain.enums import DocumentStatus, ProcessingStepName, ProcessingStepStatus
from app.modules.auth.repository import UserRepository
from app.modules.organizations.repository import OrganizationRepository


pytestmark = pytest.mark.integration


@pytest.fixture
def admin_client(admin_client_factory):
    return admin_client_factory()


@pytest.fixture
def admin_client_factory(db_session: Session):
    from app.modules.admin.app import create_admin_app

    def build(**kwargs):
        @contextmanager
        def session_scope() -> Iterator[Session]:
            yield db_session

        app = create_admin_app(session_scope=session_scope, **kwargs)
        app.config.update(TESTING=True)
        return app.test_client()

    return build


def test_admin_home_links_to_read_only_views(admin_client) -> None:
    response = admin_client.get("/")

    assert response.status_code == 200
    body = response.text
    assert "Primmo Admin" in body
    assert "/organizations" in body
    assert "/users" in body
    assert "/documents" in body


def test_admin_home_shows_filterable_dashboard_snapshot(
    admin_client,
    db_session: Session,
) -> None:
    seed_demo_data(db_session)
    alpha_document = create_document(
        db_session,
        owner_email="alpha@example.com",
        filename="lease-alpha.pdf",
        status=DocumentStatus.WAITING_PARTNER,
        external_job_id="j_dashboard_alpha",
    )
    beta_document = create_document(
        db_session,
        owner_email="beta@example.com",
        filename="lease-beta.pdf",
        status=DocumentStatus.FAILED,
        current_error_type="ConnectionError",
    )
    create_step(
        db_session,
        document=alpha_document,
        name=ProcessingStepName.PARTNER_WEBHOOK,
        status=ProcessingStepStatus.WAITING_WEBHOOK,
    )
    create_step(
        db_session,
        document=beta_document,
        name=ProcessingStepName.OCR,
        status=ProcessingStepStatus.FAILED,
    )
    alpha_org = db_session.scalar(
        select(OrganizationORM).where(OrganizationORM.name == "Primmo Alpha")
    )
    assert alpha_org is not None

    response = admin_client.get(f"/?org_id={alpha_org.id}")

    assert response.status_code == 200
    body = response.text
    assert "Dashboard" in body
    assert "Refresh snapshot" in body
    assert "Documents by status" in body
    assert "Steps by status" in body
    assert "Waiting partner" in body
    assert "lease-alpha.pdf" in body
    assert "lease-beta.pdf" not in body
    assert f'href="/documents?org_id={alpha_org.id}"' in body
    assert f'href="/users?org_id={alpha_org.id}"' in body
    assert 'href="/documents?status=waiting_partner"' in body
    assert 'href="/documents/actions?status=waiting_partner"' in body
    assert 'href="/processing-steps?step_status=waiting_webhook"' in body


def test_admin_lists_processing_steps_with_filters_and_navigation(
    admin_client,
    db_session: Session,
) -> None:
    seed_demo_data(db_session)
    alpha_document = create_document(
        db_session,
        owner_email="alpha@example.com",
        filename="lease-processing-alpha.pdf",
        status=DocumentStatus.PROCESSING,
        external_job_id="j_processing_alpha",
    )
    beta_document = create_document(
        db_session,
        owner_email="beta@example.com",
        filename="lease-processing-beta.pdf",
        status=DocumentStatus.FAILED,
    )
    alpha_step = create_step(
        db_session,
        document=alpha_document,
        name=ProcessingStepName.OCR,
        status=ProcessingStepStatus.RUNNING,
        result_json={"ocr_text": "alpha raw text"},
    )
    create_step(
        db_session,
        document=beta_document,
        name=ProcessingStepName.METADATA,
        status=ProcessingStepStatus.FAILED,
    )

    response = admin_client.get(
        "/processing-steps"
        f"?org_id={alpha_document.org_id}"
        f"&owner_user_id={alpha_document.owner_user_id}"
        "&document_status=processing"
        "&step_name=ocr"
        "&step_status=running"
        "&q=alpha"
    )

    assert response.status_code == 200
    body = response.text
    assert "Processing steps" in body
    assert "lease-processing-alpha.pdf" in body
    assert "lease-processing-beta.pdf" not in body
    assert "ocr" in body
    assert "running" in body
    assert f'value="{alpha_document.org_id}" selected' in body
    assert f'value="{alpha_document.owner_user_id}" selected' in body
    assert 'value="processing" selected' in body
    assert 'value="ocr" selected' in body
    assert 'value="running" selected' in body
    assert 'value="alpha"' in body
    assert f'href="/documents/{alpha_document.id}"' in body
    assert f'href="/documents/{alpha_document.id}/actions"' in body
    assert f'href="/processing-steps?document_id={alpha_document.id}"' in body
    assert alpha_step.updated_by in body
    assert "alpha raw text" in body


def test_admin_lists_organizations_and_counts(admin_client, db_session: Session) -> None:
    seed_demo_data(db_session)
    create_document(db_session, owner_email="alpha@example.com")
    organization = db_session.scalar(
        select(OrganizationORM).where(OrganizationORM.name == "Primmo Alpha")
    )
    assert organization is not None

    response = admin_client.get("/organizations")

    assert response.status_code == 200
    body = response.text
    assert "Primmo Alpha" in body
    assert "Primmo Beta" in body
    assert "1 document" in body
    assert "1 user" in body
    assert f'href="/users?org_id={organization.id}"' in body
    assert f'href="/documents?org_id={organization.id}"' in body


def test_admin_filters_organizations_by_name(admin_client, db_session: Session) -> None:
    seed_demo_data(db_session)

    response = admin_client.get("/organizations?q=Alpha")

    assert response.status_code == 200
    body = response.text
    assert "Primmo Alpha" in body
    assert "Primmo Beta" not in body
    assert 'name="q"' in body
    assert 'value="Alpha"' in body


def test_admin_lists_users_with_organization(admin_client, db_session: Session) -> None:
    seed_demo_data(db_session)
    create_document(db_session, owner_email="alpha@example.com")
    alpha_user = UserRepository(db_session).get_by_email("alpha@example.com")
    assert alpha_user is not None

    response = admin_client.get("/users")

    assert response.status_code == 200
    body = response.text
    assert "alpha@example.com" in body
    assert "Primmo Alpha" in body
    assert "beta@example.com" in body
    assert "Primmo Beta" in body
    assert "1 document" in body
    assert f'href="/documents?owner_user_id={alpha_user.id}"' in body


def test_admin_filters_users_by_organization(admin_client, db_session: Session) -> None:
    seed_demo_data(db_session)
    organization = db_session.scalar(
        select(OrganizationORM).where(OrganizationORM.name == "Primmo Alpha")
    )
    assert organization is not None

    response = admin_client.get(f"/users?org_id={organization.id}")

    assert response.status_code == 200
    body = response.text
    assert "alpha@example.com" in body
    assert "beta@example.com" not in body
    assert f'value="{organization.id}" selected' in body


def test_admin_lists_documents_with_owner_and_status(
    admin_client,
    db_session: Session,
) -> None:
    seed_demo_data(db_session)
    document = create_document(
        db_session,
        owner_email="alpha@example.com",
        filename="lease-alpha.pdf",
        status=DocumentStatus.WAITING_PARTNER,
        external_job_id="j_admin_test",
        current_error_type="TimeoutError",
    )

    response = admin_client.get("/documents")

    assert response.status_code == 200
    body = response.text
    assert "lease-alpha.pdf" in body
    assert "Primmo Alpha" in body
    assert "alpha@example.com" in body
    assert "waiting_partner" in body
    assert "j_admin_test" in body
    assert "TimeoutError" in body
    assert f"/documents/{document.id}" in body
    assert "/documents/new" in body
    assert "Add documents" in body
    assert 'id="documents-action-form"' in body
    assert 'action="/documents/actions"' in body
    assert 'id="select-all-documents"' in body
    assert f'name="rowid" value="{document.id}"' in body
    assert 'name="action"' in body
    assert 'value="partner_webhook_completed"' in body
    assert 'value="partner_webhook_rejected"' in body
    assert "Validate document" in body
    assert "Invalidate document" in body
    assert "Apply action" in body
    assert "0 selected" in body
    assert f'href="/users?org_id={document.org_id}"' in body
    assert f'href="/documents?org_id={document.org_id}"' in body
    assert f'href="/documents?owner_user_id={document.owner_user_id}"' in body
    assert f'href="/documents/{document.id}/actions"' in body


def test_admin_filters_documents_by_status_org_owner_and_text(
    admin_client,
    db_session: Session,
) -> None:
    seed_demo_data(db_session)
    alpha_document = create_document(
        db_session,
        owner_email="alpha@example.com",
        filename="lease-alpha.pdf",
        status=DocumentStatus.WAITING_PARTNER,
        external_job_id="j_filter_alpha",
    )
    create_document(
        db_session,
        owner_email="beta@example.com",
        filename="lease-beta.pdf",
        status=DocumentStatus.FAILED,
        external_job_id="j_filter_beta",
    )

    response = admin_client.get(
        "/documents"
        f"?org_id={alpha_document.org_id}"
        f"&owner_user_id={alpha_document.owner_user_id}"
        "&status=waiting_partner"
        "&q=alpha"
    )

    assert response.status_code == 200
    body = response.text
    assert "lease-alpha.pdf" in body
    assert "lease-beta.pdf" not in body
    assert f'value="{alpha_document.org_id}" selected' in body
    assert f'value="{alpha_document.owner_user_id}" selected' in body
    assert 'value="waiting_partner" selected' in body
    assert 'value="alpha"' in body


def test_admin_document_actions_page_lists_actionable_documents(
    admin_client,
    db_session: Session,
) -> None:
    seed_demo_data(db_session)
    actionable_document = create_document(
        db_session,
        owner_email="alpha@example.com",
        filename="lease-actionable.pdf",
        status=DocumentStatus.WAITING_PARTNER,
        external_job_id="j_actionable",
    )
    create_document(
        db_session,
        owner_email="beta@example.com",
        filename="lease-not-actionable.pdf",
        status=DocumentStatus.PROCESSING,
    )

    response = admin_client.get("/documents/actions")

    assert response.status_code == 200
    body = response.text
    assert "Document actions" in body
    assert "lease-actionable.pdf" in body
    assert "lease-not-actionable.pdf" not in body
    assert f'href="/documents/{actionable_document.id}/actions"' in body
    assert 'name="status"' in body
    assert 'value="waiting_partner" selected' in body


def test_admin_single_document_action_page_shows_webhook_payload(
    admin_client,
    db_session: Session,
) -> None:
    seed_demo_data(db_session)
    document = create_document(
        db_session,
        owner_email="alpha@example.com",
        filename="lease-single-action.pdf",
        status=DocumentStatus.WAITING_PARTNER,
        external_job_id="j_single_action",
    )
    create_step(
        db_session,
        document=document,
        name=ProcessingStepName.PARTNER_WEBHOOK,
        status=ProcessingStepStatus.WAITING_WEBHOOK,
    )

    response = admin_client.get(f"/documents/{document.id}/actions")

    assert response.status_code == 200
    body = response.text
    assert "Document action" in body
    assert "Webhook payload preview" in body
    assert "lease-single-action.pdf" in body
    assert "j_single_action" in body
    assert f'name="rowid" value="{document.id}"' in body
    assert 'value="partner_webhook_completed"' in body
    assert 'value="partner_webhook_rejected"' in body
    assert "Validate document" in body
    assert "Invalidate document" in body
    assert '"job_id":"j_single_action"' in body
    assert 'value="pipeline_relaunch:all"' in body
    assert 'value="pipeline_relaunch:ocr"' in body
    assert 'value="pipeline_relaunch:post_ocr"' in body
    assert 'value="pipeline_relaunch:metadata"' in body
    assert 'value="pipeline_relaunch:chunking"' in body
    assert 'value="pipeline_relaunch:external_call"' in body


def test_admin_single_document_action_form_applies_webhook(
    admin_client,
    db_session: Session,
) -> None:
    seed_demo_data(db_session)
    document = create_document(
        db_session,
        owner_email="alpha@example.com",
        filename="lease-form-action.pdf",
        status=DocumentStatus.WAITING_PARTNER,
        external_job_id="j_form_action",
    )
    create_step(
        db_session,
        document=document,
        name=ProcessingStepName.PARTNER_WEBHOOK,
        status=ProcessingStepStatus.WAITING_WEBHOOK,
    )

    response = admin_client.post(
        "/documents/actions",
        data={
            "action": "partner_webhook_completed",
            "rowid": str(document.id),
        },
    )

    assert response.status_code == 200
    body = response.text
    assert "Partner webhook completed" in body
    assert "lease-form-action.pdf" in body
    assert "j_form_action" in body


def test_admin_completes_selected_partner_webhooks(
    admin_client,
    db_session: Session,
) -> None:
    seed_demo_data(db_session)
    first_document = create_document(
        db_session,
        owner_email="alpha@example.com",
        filename="lease-alpha.pdf",
        status=DocumentStatus.WAITING_PARTNER,
        external_job_id="j_admin_first",
    )
    second_document = create_document(
        db_session,
        owner_email="beta@example.com",
        filename="lease-beta.pdf",
        status=DocumentStatus.WAITING_PARTNER,
        external_job_id="j_admin_second",
    )
    for document in (first_document, second_document):
        create_step(
            db_session,
            document=document,
            name=ProcessingStepName.PARTNER_WEBHOOK,
            status=ProcessingStepStatus.WAITING_WEBHOOK,
        )

    response = admin_client.post(
        "/documents/actions",
        data={
            "action": "partner_webhook_completed",
            "rowid": [str(first_document.id), str(second_document.id)],
        },
    )

    assert response.status_code == 200
    body = response.text
    assert "Partner webhook completed" in body
    assert "lease-alpha.pdf" in body
    assert "lease-beta.pdf" in body
    assert "j_admin_first" in body
    assert "j_admin_second" in body
    assert "X-Partner-Signature" in body

    first_row = db_session.get(DocumentORM, first_document.id)
    second_row = db_session.get(DocumentORM, second_document.id)
    assert first_row is not None
    assert second_row is not None
    assert first_row.status == DocumentStatus.READY.value
    assert second_row.status == DocumentStatus.READY.value

    first_data = db_session.get(ExtractedDataORM, first_document.id)
    second_data = db_session.get(ExtractedDataORM, second_document.id)
    assert first_data is not None
    assert second_data is not None
    assert first_data.partner_result_json["source"] == "admin"
    assert second_data.partner_result_json["source"] == "admin"

    first_step = get_step(db_session, first_document, ProcessingStepName.PARTNER_WEBHOOK)
    second_step = get_step(db_session, second_document, ProcessingStepName.PARTNER_WEBHOOK)
    assert first_step.status == ProcessingStepStatus.SUCCESS.value
    assert second_step.status == ProcessingStepStatus.SUCCESS.value


def test_admin_rejects_selected_partner_webhooks(
    admin_client,
    db_session: Session,
) -> None:
    seed_demo_data(db_session)
    first_document = create_document(
        db_session,
        owner_email="alpha@example.com",
        filename="lease-alpha.pdf",
        status=DocumentStatus.WAITING_PARTNER,
        external_job_id="j_admin_reject_first",
    )
    second_document = create_document(
        db_session,
        owner_email="beta@example.com",
        filename="lease-beta.pdf",
        status=DocumentStatus.WAITING_PARTNER,
        external_job_id="j_admin_reject_second",
    )
    for document in (first_document, second_document):
        create_step(
            db_session,
            document=document,
            name=ProcessingStepName.PARTNER_WEBHOOK,
            status=ProcessingStepStatus.WAITING_WEBHOOK,
        )

    response = admin_client.post(
        "/documents/actions",
        data={
            "action": "partner_webhook_rejected",
            "rowid": [str(first_document.id), str(second_document.id)],
        },
    )

    assert response.status_code == 200
    body = response.text
    assert "Partner webhook rejected" in body
    assert "lease-alpha.pdf" in body
    assert "lease-beta.pdf" in body
    assert "j_admin_reject_first" in body
    assert "j_admin_reject_second" in body
    assert "X-Partner-Signature" in body

    first_row = db_session.get(DocumentORM, first_document.id)
    second_row = db_session.get(DocumentORM, second_document.id)
    assert first_row is not None
    assert second_row is not None
    assert first_row.status == DocumentStatus.FAILED.value
    assert second_row.status == DocumentStatus.FAILED.value
    assert first_row.current_error_type == "PartnerWebhookFailed"
    assert second_row.current_error_type == "PartnerWebhookFailed"
    assert first_row.current_error_message == "partner returned status rejected"
    assert second_row.current_error_message == "partner returned status rejected"

    first_step = get_step(db_session, first_document, ProcessingStepName.PARTNER_WEBHOOK)
    second_step = get_step(db_session, second_document, ProcessingStepName.PARTNER_WEBHOOK)
    assert first_step.status == ProcessingStepStatus.FAILED.value
    assert second_step.status == ProcessingStepStatus.FAILED.value


def test_admin_relaunches_selected_documents_from_ocr(
    admin_client_factory,
    db_session: Session,
) -> None:
    seed_demo_data(db_session)
    first_document = create_document(
        db_session,
        owner_email="alpha@example.com",
        filename="lease-rerun-first.pdf",
        status=DocumentStatus.FAILED,
        external_job_id="j_rerun_first",
        current_error_type="ConnectionError",
    )
    second_document = create_document(
        db_session,
        owner_email="beta@example.com",
        filename="lease-rerun-second.pdf",
        status=DocumentStatus.READY,
        external_job_id="j_rerun_second",
    )
    for document in (first_document, second_document):
        db_session.add(
            ExtractedDataORM(
                document_id=document.id,
                ocr_text="old ocr",
                metadata_json={"old": "metadata"},
                chunks_json=["old chunk"],
                partner_result_json={"old": "partner"},
            )
        )
        create_step(
            db_session,
            document=document,
            name=ProcessingStepName.OCR,
            status=ProcessingStepStatus.FAILED,
        )

    pipeline = FakePipeline()
    admin_client = admin_client_factory(pipeline_factory=lambda: pipeline)

    response = admin_client.post(
        "/documents/actions",
        data={
            "action": "pipeline_relaunch:ocr",
            "rowid": [str(first_document.id), str(second_document.id)],
        },
    )

    assert response.status_code == 200
    body = response.text
    assert "Pipeline relaunch results" in body
    assert "Pipeline queued" in body
    assert "lease-rerun-first.pdf" in body
    assert "lease-rerun-second.pdf" in body
    assert pipeline.enqueued == [
        (first_document.id, "ocr"),
        (second_document.id, "ocr"),
    ]

    for document in (first_document, second_document):
        row = db_session.get(DocumentORM, document.id)
        assert row is not None
        assert row.status == DocumentStatus.PROCESSING.value
        assert row.external_job_id is None
        assert row.current_error_type is None

        extracted = db_session.get(ExtractedDataORM, document.id)
        assert extracted is not None
        assert extracted.ocr_text is None
        assert extracted.metadata_json is None
        assert extracted.chunks_json is None
        assert extracted.partner_result_json is None

        assert get_step(db_session, document, ProcessingStepName.OCR).status == ProcessingStepStatus.PENDING.value
        assert (
            get_step(db_session, document, ProcessingStepName.METADATA).status
            == ProcessingStepStatus.PENDING.value
        )
        assert (
            get_step(db_session, document, ProcessingStepName.CHUNKING).status
            == ProcessingStepStatus.PENDING.value
        )
        assert (
            get_step(db_session, document, ProcessingStepName.EXTERNAL_CALL).status
            == ProcessingStepStatus.PENDING.value
        )
        assert (
            get_step(db_session, document, ProcessingStepName.PARTNER_WEBHOOK).status
            == ProcessingStepStatus.PENDING.value
        )


def test_admin_relaunch_metadata_preserves_required_outputs(
    admin_client_factory,
    db_session: Session,
) -> None:
    seed_demo_data(db_session)
    document = create_document(
        db_session,
        owner_email="alpha@example.com",
        filename="lease-rerun-metadata.pdf",
        status=DocumentStatus.READY,
        external_job_id="j_rerun_metadata",
    )
    db_session.add(
        ExtractedDataORM(
            document_id=document.id,
            ocr_text="existing ocr",
            metadata_json={"old": "metadata"},
            chunks_json=["existing chunk"],
            partner_result_json={"old": "partner"},
        )
    )
    create_step(
        db_session,
        document=document,
        name=ProcessingStepName.METADATA,
        status=ProcessingStepStatus.SUCCESS,
    )
    create_step(
        db_session,
        document=document,
        name=ProcessingStepName.EXTERNAL_CALL,
        status=ProcessingStepStatus.SUCCESS,
    )

    pipeline = FakePipeline()
    admin_client = admin_client_factory(pipeline_factory=lambda: pipeline)

    response = admin_client.post(
        "/documents/actions",
        data={
            "action": "pipeline_relaunch:metadata",
            "rowid": str(document.id),
        },
    )

    assert response.status_code == 200
    assert "Pipeline queued" in response.text
    assert pipeline.enqueued == [(document.id, "metadata")]

    extracted = db_session.get(ExtractedDataORM, document.id)
    assert extracted is not None
    assert extracted.ocr_text == "existing ocr"
    assert extracted.metadata_json is None
    assert extracted.chunks_json == ["existing chunk"]
    assert extracted.partner_result_json is None

    row = db_session.get(DocumentORM, document.id)
    assert row is not None
    assert row.status == DocumentStatus.PROCESSING.value
    assert row.external_job_id is None
    assert get_step(db_session, document, ProcessingStepName.METADATA).status == ProcessingStepStatus.PENDING.value
    assert (
        get_step(db_session, document, ProcessingStepName.EXTERNAL_CALL).status
        == ProcessingStepStatus.PENDING.value
    )
    assert (
        get_step(db_session, document, ProcessingStepName.PARTNER_WEBHOOK).status
        == ProcessingStepStatus.PENDING.value
    )


def test_admin_relaunch_skips_when_required_outputs_are_missing(
    admin_client_factory,
    db_session: Session,
) -> None:
    seed_demo_data(db_session)
    document = create_document(
        db_session,
        owner_email="alpha@example.com",
        filename="lease-rerun-skipped.pdf",
        status=DocumentStatus.UPLOADED,
    )
    pipeline = FakePipeline()
    admin_client = admin_client_factory(pipeline_factory=lambda: pipeline)

    response = admin_client.post(
        "/documents/actions",
        data={
            "action": "pipeline_relaunch:external_call",
            "rowid": str(document.id),
        },
    )

    assert response.status_code == 200
    body = response.text
    assert "Missing required output: ocr, metadata, chunks." in body
    assert pipeline.enqueued == []

    row = db_session.get(DocumentORM, document.id)
    assert row is not None
    assert row.status == DocumentStatus.UPLOADED.value


def test_admin_new_documents_form_lists_users(admin_client, db_session: Session) -> None:
    seed_demo_data(db_session)

    response = admin_client.get("/documents/new")

    assert response.status_code == 200
    body = response.text
    assert "Add documents" in body
    assert 'name="owner_user_id"' in body
    assert 'name="files"' in body
    assert "multiple" in body
    assert "alpha@example.com" in body
    assert "Primmo Alpha" in body
    assert "beta@example.com" in body
    assert "Primmo Beta" in body
    assert 'action="/documents/generate-fake-batch"' in body
    assert 'name="organization_name"' in body
    assert 'value="Load Test Org"' in body
    assert 'name="user_count"' in body
    assert 'value="50"' in body
    assert 'name="document_count"' in body
    assert 'value="200"' in body
    assert 'name="filename_prefix"' in body
    assert 'value="load-test-lease"' in body


def test_admin_test_cockpit_exposes_technical_test_workflows(
    admin_client,
    db_session: Session,
) -> None:
    seed_demo_data(db_session)
    waiting_document = create_document(
        db_session,
        owner_email="alpha@example.com",
        filename="lease-cockpit.pdf",
        status=DocumentStatus.WAITING_PARTNER,
        external_job_id="j_cockpit_alpha",
    )

    response = admin_client.get("/test-cockpit")

    assert response.status_code == 200
    body = response.text
    assert "Test cockpit" in body
    assert "Create documents for a user" in body
    assert 'action="/test-cockpit/documents"' in body
    assert 'name="owner_user_id"' in body
    assert 'name="document_count"' in body
    assert 'name="filename_prefix"' in body
    assert "alpha@example.com" in body
    assert "Primmo Alpha" in body
    assert "Action queue" in body
    assert 'action="/documents/actions"' in body
    assert 'value="partner_webhook_completed"' in body
    assert 'value="partner_webhook_rejected"' in body
    assert 'value="pipeline_relaunch:all"' in body
    assert 'value="pipeline_relaunch:ocr"' in body
    assert 'href="/documents/new"' in body
    assert 'href="/processing-steps"' in body
    assert f'href="/documents/{waiting_document.id}"' in body
    assert f'href="/documents/{waiting_document.id}/actions"' in body
    assert "j_cockpit_alpha" in body


def test_admin_test_cockpit_creates_requested_fake_documents_for_user(
    admin_client_factory,
    db_session: Session,
) -> None:
    seed_demo_data(db_session)
    user = UserRepository(db_session).get_by_email("alpha@example.com")
    assert user is not None
    storage = FakeStorage()
    pipeline = FakePipeline()
    admin_client = admin_client_factory(
        storage_factory=lambda: storage,
        pipeline_factory=lambda: pipeline,
    )

    response = admin_client.post(
        "/test-cockpit/documents",
        data={
            "owner_user_id": str(user.id),
            "document_count": "3",
            "filename_prefix": "cockpit-lease",
        },
    )

    assert response.status_code == 200
    body = response.text
    assert "Documents created" in body
    assert "3 documents created" in body
    assert "cockpit-lease-001.pdf" in body
    assert "cockpit-lease-003.pdf" in body
    assert "Queued pipeline" in body

    documents = db_session.scalars(
        select(DocumentORM)
        .where(DocumentORM.owner_user_id == user.id)
        .order_by(DocumentORM.original_filename)
    ).all()
    assert [document.original_filename for document in documents] == [
        "cockpit-lease-001.pdf",
        "cockpit-lease-002.pdf",
        "cockpit-lease-003.pdf",
    ]
    assert {document.id for document in documents} == set(pipeline.enqueued_document_ids)
    assert len(storage.objects) == 3
    assert all("/users/alpha-example-com/" in key[1] for key in storage.objects)


def test_admin_uploads_documents_for_user_and_enqueues_pipelines(
    admin_client_factory,
    db_session: Session,
) -> None:
    seed_demo_data(db_session)
    user = UserRepository(db_session).get_by_email("alpha@example.com")
    assert user is not None
    storage = FakeStorage()
    pipeline = FakePipeline()
    admin_client = admin_client_factory(
        storage_factory=lambda: storage,
        pipeline_factory=lambda: pipeline,
    )

    response = admin_client.post(
        "/documents/new",
        data={
            "owner_user_id": str(user.id),
            "files": [
                (BytesIO(b"%PDF-1 admin lease alpha"), "lease-alpha.pdf", "application/pdf"),
                (BytesIO(b"%PDF-1 admin lease beta"), "lease beta.pdf", "application/pdf"),
            ],
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    body = response.text
    assert "Documents created" in body
    assert "lease-alpha.pdf" in body
    assert "lease beta.pdf" in body
    assert "Queued pipeline" in body

    documents = db_session.scalars(
        select(DocumentORM)
        .where(DocumentORM.owner_user_id == user.id)
        .order_by(DocumentORM.original_filename)
    ).all()
    assert [document.original_filename for document in documents] == [
        "lease beta.pdf",
        "lease-alpha.pdf",
    ]
    assert [document.status for document in documents] == [
        DocumentStatus.UPLOADED.value,
        DocumentStatus.UPLOADED.value,
    ]
    assert {document.id for document in documents} == set(pipeline.enqueued_document_ids)
    assert len(storage.objects) == 2
    assert all(key[0] == "primmo-documents" for key in storage.objects)
    assert all("/users/alpha-example-com/" in key[1] for key in storage.objects)


def test_admin_generates_fake_batch_for_specific_org_and_enqueues_pipelines(
    admin_client_factory,
    db_session: Session,
) -> None:
    storage = FakeStorage()
    pipeline = FakePipeline()
    admin_client = admin_client_factory(
        storage_factory=lambda: storage,
        pipeline_factory=lambda: pipeline,
    )

    response = admin_client.post(
        "/documents/generate-fake-batch",
        data={
            "organization_name": "Load Target Org",
            "user_count": "50",
            "document_count": "200",
            "filename_prefix": "load-target-lease",
        },
    )

    assert response.status_code == 200
    body = response.text
    assert "Documents created" in body
    assert "200 documents created" in body
    assert "Queued pipeline" in body

    organization = db_session.scalar(
        select(OrganizationORM).where(OrganizationORM.name == "Load Target Org")
    )
    assert organization is not None
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(UserORM)
            .where(UserORM.org_id == organization.id)
        )
        == 50
    )
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(DocumentORM)
            .where(DocumentORM.org_id == organization.id)
        )
        == 200
    )
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(DocumentORM)
            .where(
                DocumentORM.org_id == organization.id,
                DocumentORM.status == DocumentStatus.UPLOADED.value,
            )
        )
        == 200
    )
    assert len(storage.objects) == 200
    assert len(pipeline.enqueued_document_ids) == 200
    assert all(key[0] == "primmo-documents" for key in storage.objects)
    assert all(key[1].startswith("orgs/load-target-org/") for key in storage.objects)


def test_admin_document_detail_lists_processing_steps(
    admin_client,
    db_session: Session,
) -> None:
    seed_demo_data(db_session)
    document = create_document(
        db_session,
        owner_email="alpha@example.com",
        filename="lease-alpha.pdf",
        status=DocumentStatus.PROCESSING,
    )
    create_step(
        db_session,
        document=document,
        name=ProcessingStepName.OCR,
        status=ProcessingStepStatus.SUCCESS,
        result_json={"ocr_text": "lease raw text"},
    )
    create_step(
        db_session,
        document=document,
        name=ProcessingStepName.METADATA,
        status=ProcessingStepStatus.RUNNING,
    )

    response = admin_client.get(f"/documents/{document.id}")

    assert response.status_code == 200
    body = response.text
    assert "lease-alpha.pdf" in body
    assert "Primmo Alpha" in body
    assert "alpha@example.com" in body
    assert "processing" in body
    assert "ocr" in body
    assert "success" in body
    assert "lease raw text" in body
    assert "metadata" in body
    assert "running" in body


def create_document(
    db_session: Session,
    *,
    owner_email: str,
    filename: str = "lease.pdf",
    status: DocumentStatus = DocumentStatus.WAITING_UPLOAD,
    external_job_id: str | None = None,
    current_error_type: str | None = None,
) -> DocumentORM:
    user = UserRepository(db_session).get_by_email(owner_email)
    assert user is not None
    organization = OrganizationRepository(db_session).get(user.org_id)
    assert organization is not None
    document_id = uuid4()
    document = DocumentORM(
        id=document_id,
        org_id=user.org_id,
        owner_user_id=user.id,
        original_filename=filename,
        content_type="application/pdf",
        size_bytes=1024,
        storage_bucket="primmo-documents",
        storage_key=(
            f"orgs/{organization.name.lower().replace(' ', '-')}/"
            f"users/{owner_email.replace('@', '-').replace('.', '-')}/"
            f"documents/{document_id}/{filename.replace('.pdf', '').replace(' ', '-').lower()}.pdf"
        ),
        status=status.value,
        external_job_id=external_job_id,
        current_error_type=current_error_type,
    )
    db_session.add(document)
    db_session.flush()
    return document


def create_step(
    db_session: Session,
    *,
    document: DocumentORM,
    name: ProcessingStepName,
    status: ProcessingStepStatus,
    result_json: dict | None = None,
) -> ProcessingStepORM:
    step = ProcessingStepORM(
        id=uuid4(),
        document_id=document.id,
        name=name.value,
        status=status.value,
        attempt_count=1,
        result_json=result_json,
        updated_by="test",
    )
    db_session.add(step)
    db_session.flush()
    return step


def get_step(
    db_session: Session,
    document: DocumentORM,
    name: ProcessingStepName,
) -> ProcessingStepORM:
    step = db_session.scalar(
        select(ProcessingStepORM).where(
            ProcessingStepORM.document_id == document.id,
            ProcessingStepORM.name == name.value,
        )
    )
    assert step is not None
    return step


class FakeStorage:
    def __init__(self):
        self.objects = {}

    def put_object(
        self,
        *,
        bucket: str,
        key: str,
        content: bytes,
        content_type: str,
    ) -> None:
        self.objects[(bucket, key)] = {
            "content": content,
            "content_type": content_type,
        }

    def object_exists(self, *, bucket: str, key: str) -> bool:
        return (bucket, key) in self.objects


class FakePipeline:
    def __init__(self):
        self.enqueued_document_ids: list[UUID] = []
        self.enqueued: list[tuple[UUID, str]] = []

    def enqueue_full_pipeline(self, document_id: UUID) -> str:
        self.enqueued_document_ids.append(document_id)
        return f"task-{len(self.enqueued_document_ids)}"

    def enqueue(self, document_id: UUID, strategy=None) -> str:
        strategy_value = getattr(strategy, "value", strategy) or "all"
        self.enqueued.append((document_id, strategy_value))
        return f"task-{len(self.enqueued)}"
