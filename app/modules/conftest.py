from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from app.db.models import DocumentORM, OrganizationORM, ProcessingStepORM, UserORM
from app.db.session import get_db_session
from app.db.tests.conftest import db_session as db_session
from app.db.tests.conftest import test_database_url as test_database_url
from app.db.tests.conftest import test_engine as test_engine
from app.domain.enums import DocumentStatus, ProcessingStepName, ProcessingStepStatus
from app.domain.models import CreateDocumentCommand, CreateDocumentRecord, DocumentState
from app.main import create_app


@pytest.fixture
def api_client(db_session):
    from fastapi.testclient import TestClient

    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: db_session

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
def org_id() -> UUID:
    return uuid4()


@pytest.fixture
def owner_user_id() -> UUID:
    return uuid4()


@pytest.fixture
def document_id() -> UUID:
    return uuid4()


@pytest.fixture
def persisted_org_user(
    db_session: Session,
    org_id: UUID,
    owner_user_id: UUID,
) -> tuple[OrganizationORM, UserORM]:
    organization = OrganizationORM(id=org_id, name=f"Org {org_id.hex[:8]}")
    user = UserORM(
        id=owner_user_id,
        org_id=org_id,
        email=f"{owner_user_id.hex}@example.com",
        password_hash="hashed-password",
    )
    db_session.add_all([organization, user])
    db_session.flush()
    return organization, user


@pytest.fixture
def create_document_record(
    document_id: UUID,
    org_id: UUID,
    owner_user_id: UUID,
) -> CreateDocumentRecord:
    return CreateDocumentRecord(
        id=document_id,
        org_id=org_id,
        owner_user_id=owner_user_id,
        original_filename="lease.pdf",
        content_type="application/pdf",
        size_bytes=1024,
        storage_bucket="primmo-documents",
        storage_key=(
            f"orgs/org-{org_id.hex[:8]}/users/user-{owner_user_id.hex[:8]}-example-com/"
            f"documents/{document_id}/lease.pdf"
        ),
        status=DocumentStatus.WAITING_UPLOAD,
    )


@pytest.fixture
def create_document_command(org_id: UUID, owner_user_id: UUID) -> CreateDocumentCommand:
    return CreateDocumentCommand(
        org_id=org_id,
        org_name=f"Org {org_id.hex[:8]}",
        owner_user_id=owner_user_id,
        owner_user_email=f"user-{owner_user_id.hex[:8]}@example.com",
        filename="lease.pdf",
        content_type="application/pdf",
        size_bytes=1024,
    )


@pytest.fixture
def document_state(
    document_id: UUID,
    create_document_command: CreateDocumentCommand,
) -> DocumentState:
    return DocumentState(
        id=document_id,
        org_id=create_document_command.org_id,
        owner_user_id=create_document_command.owner_user_id,
        original_filename=create_document_command.filename,
        content_type=create_document_command.content_type,
        size_bytes=create_document_command.size_bytes,
        storage_bucket="primmo-documents",
        storage_key=(
            f"orgs/{create_document_command.org_name.lower().replace(' ', '-')}/"
            f"users/user-{create_document_command.owner_user_id.hex[:8]}-example-com/"
            f"documents/{document_id}/lease.pdf"
        ),
        status=DocumentStatus.WAITING_UPLOAD,
        external_job_id=None,
        current_error_type=None,
        current_error_message=None,
    )


@pytest.fixture
def document_row(document_id: UUID, org_id: UUID, owner_user_id: UUID) -> DocumentORM:
    return DocumentORM(
        id=document_id,
        org_id=org_id,
        owner_user_id=owner_user_id,
        original_filename="lease.pdf",
        content_type="application/pdf",
        size_bytes=1024,
        storage_bucket="primmo-documents",
        storage_key=(
            f"orgs/org-{org_id.hex[:8]}/users/user-{owner_user_id.hex[:8]}-example-com/"
            f"documents/{document_id}/lease.pdf"
        ),
        status=DocumentStatus.WAITING_UPLOAD.value,
    )


@pytest.fixture
def processing_step_row(document_id: UUID) -> ProcessingStepORM:
    return ProcessingStepORM(
        id=uuid4(),
        document_id=document_id,
        name=ProcessingStepName.OCR.value,
        status=ProcessingStepStatus.PENDING.value,
        attempt_count=0,
    )


@pytest.fixture
def document_repository() -> Mock:
    return Mock(name="DocumentRepository")


@pytest.fixture
def step_repository() -> Mock:
    return Mock(name="ProcessingStepRepository")


@pytest.fixture
def extracted_data_repository() -> Mock:
    return Mock(name="ExtractedDataRepository")
