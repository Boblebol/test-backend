import pytest
from sqlalchemy.orm import Session

from app.db.models import ExtractedDataORM
from app.domain.enums import DocumentStatus, ProcessingStepName, ProcessingStepStatus
from app.domain.models import CreateDocumentRecord
from app.modules.documents.repository import DocumentRepository
from app.modules.processing.chunking.task.chunking import chunk_document_in_session
from app.modules.processing.external_call.task.external_call import call_external_partner_in_session
from app.modules.processing.initialization.task.process_document import process_document_in_session
from app.modules.processing.metadata.task.metadata import extract_metadata_in_session
from app.modules.processing.ocr.task.ocr import ocr_document_in_session
from app.modules.processing.result_repository import ExtractedDataRepository
from app.modules.processing.step_repository import ProcessingStepRepository

pytestmark = pytest.mark.integration


def test_process_document_task_initializes_pipeline_state(
    db_session: Session,
    persisted_org_user: object,
    create_document_record: CreateDocumentRecord,
) -> None:
    uploaded_record = CreateDocumentRecord(
        **{
            **create_document_record.__dict__,
            "status": DocumentStatus.UPLOADED,
        }
    )
    document = DocumentRepository(db_session).create(uploaded_record)

    process_document_in_session(str(document.id), db_session)
    db_session.flush()

    updated_document = DocumentRepository(db_session).get(document.id)
    assert updated_document is not None
    assert updated_document.status is DocumentStatus.PROCESSING
    assert db_session.get(ExtractedDataORM, document.id) is not None
    steps = ProcessingStepRepository(db_session).list_for_document(document.id)
    assert {step.name for step in steps} == set(ProcessingStepName)
    assert {step.status for step in steps} == {ProcessingStepStatus.PENDING}
    assert {step.updated_by for step in steps} == {"celery"}


def test_process_document_task_rejects_invalid_document_id(db_session: Session) -> None:
    with pytest.raises(ValueError, match="badly formed hexadecimal UUID string"):
        process_document_in_session("not-a-uuid", db_session)


def test_ocr_task_stores_text_and_marks_step_success(
    db_session: Session,
    persisted_org_user: object,
    create_document_record: CreateDocumentRecord,
) -> None:
    document = create_uploaded_document(db_session, create_document_record)

    ocr_document_in_session(str(document.id), db_session, ocr_func=lambda: "lease raw text")
    db_session.flush()

    extracted = ExtractedDataRepository(db_session).get(document.id)
    step = step_state(db_session, document.id, ProcessingStepName.OCR)
    assert extracted is not None
    assert extracted.ocr_text == "lease raw text"
    assert step.status is ProcessingStepStatus.SUCCESS
    assert step.result_json == {"ocr_text": "lease raw text"}


def test_ocr_task_marks_empty_result_failed_but_keeps_debug_payload(
    db_session: Session,
    persisted_org_user: object,
    create_document_record: CreateDocumentRecord,
) -> None:
    document = create_uploaded_document(db_session, create_document_record)

    with pytest.raises(ValueError, match="OCR result is empty"):
        ocr_document_in_session(str(document.id), db_session, ocr_func=lambda: "   ")
    db_session.flush()

    extracted = ExtractedDataRepository(db_session).get(document.id)
    step = step_state(db_session, document.id, ProcessingStepName.OCR)
    updated_document = DocumentRepository(db_session).get(document.id)
    assert extracted is not None
    assert extracted.ocr_text == "   "
    assert step.status is ProcessingStepStatus.FAILED
    assert step.error_type == "ValueError"
    assert step.result_json == {"ocr_text": "   "}
    assert updated_document is not None
    assert updated_document.status is DocumentStatus.FAILED


def test_metadata_task_reads_ocr_and_stores_metadata(
    db_session: Session,
    persisted_org_user: object,
    create_document_record: CreateDocumentRecord,
) -> None:
    document = create_uploaded_document(db_session, create_document_record)
    ocr_document_in_session(str(document.id), db_session, ocr_func=lambda: "lease raw text")

    extract_metadata_in_session(
        str(document.id),
        db_session,
        metadata_func=lambda text: {"doc_type": "lease", "source_text": text},
    )
    db_session.flush()

    extracted = ExtractedDataRepository(db_session).get(document.id)
    step = step_state(db_session, document.id, ProcessingStepName.METADATA)
    assert extracted is not None
    assert extracted.metadata_json == {"doc_type": "lease", "source_text": "lease raw text"}
    assert step.status is ProcessingStepStatus.SUCCESS
    assert step.result_json == {"doc_type": "lease", "source_text": "lease raw text"}


def test_chunking_task_reads_ocr_and_stores_chunks(
    db_session: Session,
    persisted_org_user: object,
    create_document_record: CreateDocumentRecord,
) -> None:
    document = create_uploaded_document(db_session, create_document_record)
    ocr_document_in_session(str(document.id), db_session, ocr_func=lambda: "lease raw text")

    chunk_document_in_session(
        str(document.id),
        db_session,
        chunking_func=lambda text: [text, "chunk_2"],
    )
    db_session.flush()

    extracted = ExtractedDataRepository(db_session).get(document.id)
    step = step_state(db_session, document.id, ProcessingStepName.CHUNKING)
    assert extracted is not None
    assert extracted.chunks_json == ["lease raw text", "chunk_2"]
    assert step.status is ProcessingStepStatus.SUCCESS
    assert step.result_json == {"chunks": ["lease raw text", "chunk_2"]}


def test_external_call_task_stores_job_and_waits_for_webhook(
    db_session: Session,
    persisted_org_user: object,
    create_document_record: CreateDocumentRecord,
) -> None:
    document = create_uploaded_document(db_session, create_document_record)
    ocr_document_in_session(str(document.id), db_session, ocr_func=lambda: "lease raw text")
    extract_metadata_in_session(str(document.id), db_session, metadata_func=lambda text: {"doc_type": "lease"})
    chunk_document_in_session(str(document.id), db_session, chunking_func=lambda text: ["chunk_1"])

    call_external_partner_in_session(
        str(document.id),
        db_session,
        external_call_func=lambda doc_id, ocr_text, meta, chunks: f"job-{doc_id}",
    )
    db_session.flush()

    updated_document = DocumentRepository(db_session).get(document.id)
    assert updated_document is not None
    assert updated_document.external_job_id == f"job-{document.id}"
    assert updated_document.status is DocumentStatus.WAITING_PARTNER
    external_step = step_state(db_session, document.id, ProcessingStepName.EXTERNAL_CALL)
    assert external_step.status is ProcessingStepStatus.SUCCESS
    assert external_step.result_json == {"job_id": f"job-{document.id}"}
    assert step_status(db_session, document.id, ProcessingStepName.PARTNER_WEBHOOK) is (
        ProcessingStepStatus.WAITING_WEBHOOK
    )


def test_failed_wrapper_marks_step_and_document_failed(
    db_session: Session,
    persisted_org_user: object,
    create_document_record: CreateDocumentRecord,
) -> None:
    document = create_uploaded_document(db_session, create_document_record)
    ocr_document_in_session(str(document.id), db_session, ocr_func=lambda: "lease raw text")

    with pytest.raises(ValueError, match="metadata extraction failed"):
        extract_metadata_in_session(
            str(document.id),
            db_session,
            metadata_func=lambda text: (_ for _ in ()).throw(ValueError("metadata extraction failed")),
        )
    db_session.flush()

    updated_document = DocumentRepository(db_session).get(document.id)
    assert updated_document is not None
    assert updated_document.status is DocumentStatus.FAILED
    assert updated_document.current_error_type == "ValueError"
    assert updated_document.current_error_message == "metadata extraction failed"
    assert step_status(db_session, document.id, ProcessingStepName.METADATA) is ProcessingStepStatus.FAILED


def test_retryable_task_failure_marks_step_retrying_and_requests_retry(
    db_session: Session,
    persisted_org_user: object,
    create_document_record: CreateDocumentRecord,
) -> None:
    document = create_uploaded_document(db_session, create_document_record)
    task_context = FakeTaskContext(retries=0, max_retries=3)
    publisher = CollectingPublisher()

    with pytest.raises(RetryRequested):
        ocr_document_in_session(
            str(document.id),
            db_session,
            ocr_func=lambda: (_ for _ in ()).throw(TimeoutError("OCR provider timeout")),
            task_context=task_context,
            publisher=publisher,
        )
    db_session.flush()

    updated_document = DocumentRepository(db_session).get(document.id)
    step = step_state(db_session, document.id, ProcessingStepName.OCR)
    assert updated_document is not None
    assert updated_document.status is DocumentStatus.PROCESSING
    assert step.status is ProcessingStepStatus.RETRYING
    assert step.attempt_count == 1
    assert step.error_type == "TimeoutError"
    assert step.error_message == "OCR provider timeout"
    assert task_context.retry_calls == [{"countdown": 1, "error": "OCR provider timeout"}]
    assert publisher.events[-1].step is ProcessingStepName.OCR
    assert publisher.events[-1].step_status is ProcessingStepStatus.RETRYING
    assert publisher.events[-1].document_status is DocumentStatus.PROCESSING


def test_retryable_task_failure_marks_document_failed_when_retries_are_exhausted(
    db_session: Session,
    persisted_org_user: object,
    create_document_record: CreateDocumentRecord,
) -> None:
    document = create_uploaded_document(db_session, create_document_record)
    task_context = FakeTaskContext(retries=3, max_retries=3)
    publisher = CollectingPublisher()

    with pytest.raises(TimeoutError, match="OCR provider timeout"):
        ocr_document_in_session(
            str(document.id),
            db_session,
            ocr_func=lambda: (_ for _ in ()).throw(TimeoutError("OCR provider timeout")),
            task_context=task_context,
            publisher=publisher,
        )
    db_session.flush()

    updated_document = DocumentRepository(db_session).get(document.id)
    step = step_state(db_session, document.id, ProcessingStepName.OCR)
    assert updated_document is not None
    assert updated_document.status is DocumentStatus.FAILED
    assert updated_document.current_error_type == "TimeoutError"
    assert updated_document.current_error_message == "OCR provider timeout"
    assert step.status is ProcessingStepStatus.FAILED
    assert step.attempt_count == 0
    assert task_context.retry_calls == []
    assert publisher.events[-1].step_status is ProcessingStepStatus.FAILED


def create_uploaded_document(db_session: Session, record: CreateDocumentRecord):
    uploaded_record = CreateDocumentRecord(
        **{
            **record.__dict__,
            "status": DocumentStatus.UPLOADED,
        }
    )
    document = DocumentRepository(db_session).create(uploaded_record)
    process_document_in_session(str(document.id), db_session)
    db_session.flush()
    return document


def step_state(db_session: Session, document_id, name: ProcessingStepName):
    return next(
        step
        for step in ProcessingStepRepository(db_session).list_for_document(document_id)
        if step.name is name
    )


def step_status(db_session: Session, document_id, name: ProcessingStepName) -> ProcessingStepStatus:
    return step_state(db_session, document_id, name).status


class RetryRequested(Exception):
    pass


class FakeTaskRequest:
    def __init__(self, retries: int) -> None:
        self.id = "task-1"
        self.retries = retries


class FakeTaskContext:
    def __init__(self, retries: int, max_retries: int) -> None:
        self.request = FakeTaskRequest(retries)
        self.max_retries = max_retries
        self.retry_calls: list[dict[str, object]] = []

    def retry(self, *, exc: Exception, countdown: int) -> None:
        self.retry_calls.append({"error": str(exc), "countdown": countdown})
        raise RetryRequested from exc


class CollectingPublisher:
    def __init__(self) -> None:
        self.events = []

    def publish(self, event) -> None:
        self.events.append(event)
