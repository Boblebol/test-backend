import time
from collections.abc import Generator
from os import getenv
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import DocumentORM, ProcessingStepORM
from app.domain.enums import DocumentStatus, ProcessingStepName, ProcessingStepStatus


@pytest.fixture(scope="session")
def test_database_url() -> str:
    return getenv("TEST_DATABASE_URL", "postgresql+psycopg://primmo:primmo@localhost:5432/primmo")


@pytest.fixture(scope="session")
def test_engine(test_database_url: str) -> Generator[Engine, None, None]:
    engine = create_engine(test_database_url, pool_pre_ping=True)
    deadline = time.monotonic() + 15

    while True:
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            break
        except OperationalError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.2)

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(test_engine: Engine) -> Generator[Session, None, None]:
    session = Session(bind=test_engine, autoflush=False, expire_on_commit=False)
    for table in reversed(Base.metadata.sorted_tables):
        session.execute(table.delete())
    session.flush()

    yield session

    session.rollback()
    session.close()


@pytest.fixture
def document_row() -> DocumentORM:
    document_id = uuid4()
    org_id = uuid4()
    owner_user_id = uuid4()
    return DocumentORM(
        id=document_id,
        org_id=org_id,
        owner_user_id=owner_user_id,
        original_filename="lease.pdf",
        content_type="application/pdf",
        size_bytes=1024,
        storage_bucket="primmo-documents",
        storage_key=f"orgs/test-org/users/test-user/documents/{document_id}/lease.pdf",
        status=DocumentStatus.WAITING_UPLOAD.value,
    )


@pytest.fixture
def processing_step_row() -> ProcessingStepORM:
    return ProcessingStepORM(
        id=uuid4(),
        document_id=uuid4(),
        name=ProcessingStepName.OCR.value,
        status=ProcessingStepStatus.PENDING.value,
        attempt_count=0,
    )
