from datetime import datetime, timezone
from uuid import UUID

from app.domain.enums import DocumentStatus, ProcessingStepName, ProcessingStepStatus
from app.modules.processing.progress import NullProgressPublisher, ProgressEvent


class ProcessingService:
    def __init__(self, *, documents, steps, extracted_data, publisher=None):
        self.documents = documents
        self.steps = steps
        self.extracted_data = extracted_data
        self.publisher = publisher or NullProgressPublisher()

    def initialize_pipeline(self, document_id: UUID, updated_by: str = "system") -> None:
        for name in ProcessingStepName:
            self.steps.upsert(
                document_id=document_id,
                name=name,
                status=ProcessingStepStatus.PENDING,
                updated_by=updated_by,
            )
        self.extracted_data.create_empty(document_id)
        self.documents.update_status(document_id, DocumentStatus.PROCESSING)

    def mark_step_running(self, document_id: UUID, name: ProcessingStepName) -> None:
        self.steps.update_status(document_id, name, ProcessingStepStatus.RUNNING)
        self.documents.update_status(document_id, DocumentStatus.PROCESSING)
        self._publish(document_id, name, ProcessingStepStatus.RUNNING)

    def mark_step_success(self, document_id: UUID, name: ProcessingStepName) -> None:
        self.steps.update_status(document_id, name, ProcessingStepStatus.SUCCESS)
        self._publish(document_id, name, ProcessingStepStatus.SUCCESS)

    def store_ocr_result(self, document_id: UUID, text: str) -> None:
        self.extracted_data.set_ocr_text(document_id, text)
        self.steps.set_result(document_id, ProcessingStepName.OCR, {"ocr_text": text})

    def store_metadata_result(self, document_id: UUID, metadata: dict) -> None:
        self.extracted_data.set_metadata(document_id, metadata)
        self.steps.set_result(document_id, ProcessingStepName.METADATA, metadata)

    def store_chunks_result(self, document_id: UUID, chunks: list[str]) -> None:
        self.extracted_data.set_chunks(document_id, chunks)
        self.steps.set_result(document_id, ProcessingStepName.CHUNKING, {"chunks": chunks})

    def mark_waiting_partner(self, document_id: UUID, job_id: str) -> None:
        self.documents.set_external_job(document_id, job_id)
        self.steps.set_result(
            document_id,
            ProcessingStepName.EXTERNAL_CALL,
            {"job_id": job_id},
        )
        self.steps.update_status(
            document_id,
            ProcessingStepName.PARTNER_WEBHOOK,
            ProcessingStepStatus.WAITING_WEBHOOK,
        )
        self._publish(
            document_id,
            ProcessingStepName.PARTNER_WEBHOOK,
            ProcessingStepStatus.WAITING_WEBHOOK,
        )

    def mark_partner_completed(self, document_id: UUID, result: dict) -> None:
        self.extracted_data.set_partner_result(document_id, result)
        self.steps.set_result(document_id, ProcessingStepName.PARTNER_WEBHOOK, result)
        self.steps.update_status(
            document_id,
            ProcessingStepName.PARTNER_WEBHOOK,
            ProcessingStepStatus.SUCCESS,
        )
        self.documents.update_status(document_id, DocumentStatus.READY)
        self._publish(
            document_id,
            ProcessingStepName.PARTNER_WEBHOOK,
            ProcessingStepStatus.SUCCESS,
        )

    def mark_partner_failed(self, document_id: UUID, partner_status: str) -> None:
        error_type = "PartnerWebhookFailed"
        error_message = f"partner returned status {partner_status}"
        self.steps.set_result(
            document_id,
            ProcessingStepName.PARTNER_WEBHOOK,
            {"partner_status": partner_status},
        )
        self.steps.update_status(
            document_id,
            ProcessingStepName.PARTNER_WEBHOOK,
            ProcessingStepStatus.FAILED,
            error_type,
            error_message,
        )
        self.documents.mark_failed(document_id, error_type, error_message)
        self._publish(
            document_id,
            ProcessingStepName.PARTNER_WEBHOOK,
            ProcessingStepStatus.FAILED,
        )

    def mark_step_retrying(self, document_id: UUID, name: ProcessingStepName, error: Exception) -> None:
        self.steps.mark_retrying(
            document_id=document_id,
            name=name,
            error_type=type(error).__name__,
            error_message=str(error),
        )
        self.documents.update_status(document_id, DocumentStatus.PROCESSING)
        self._publish(document_id, name, ProcessingStepStatus.RETRYING)

    def mark_step_failed(self, document_id: UUID, name: ProcessingStepName, error: Exception) -> None:
        error_type = type(error).__name__
        error_message = str(error)
        self.steps.update_status(
            document_id,
            name,
            ProcessingStepStatus.FAILED,
            error_type,
            error_message,
        )
        self.documents.mark_failed(document_id, error_type, error_message)
        self._publish(document_id, name, ProcessingStepStatus.FAILED)

    def _publish(
        self,
        document_id: UUID,
        name: ProcessingStepName,
        step_status: ProcessingStepStatus,
    ) -> None:
        document = self.documents.get(document_id)
        if document is None:
            return
        self.publisher.publish(
            ProgressEvent(
                org_id=document.org_id,
                document_id=document.id,
                step=name,
                step_status=step_status,
                document_status=document.status,
                occurred_at=datetime.now(timezone.utc),
            )
        )
