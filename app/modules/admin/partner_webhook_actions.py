import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.domain.enums import DocumentStatus
from app.modules.documents.repository import DocumentRepository
from app.modules.partner_webhooks.signatures import build_partner_signature
from app.modules.processing.result_repository import ExtractedDataRepository
from app.modules.processing.service import ProcessingService
from app.modules.processing.step_repository import ProcessingStepRepository


@dataclass(frozen=True)
class AdminPartnerWebhookActionResult:
    document_id: UUID
    filename: str
    status: str
    message: str
    job_id: str | None = None
    request_body: str | None = None
    signature: str | None = None


class AdminPartnerWebhookActions:
    def __init__(self, session: Session, *, hmac_secret: str):
        self.documents = DocumentRepository(session)
        self.processing = ProcessingService(
            documents=self.documents,
            steps=ProcessingStepRepository(session),
            extracted_data=ExtractedDataRepository(session),
        )
        self.hmac_secret = hmac_secret

    def complete_documents(self, document_ids: list[UUID]) -> list[AdminPartnerWebhookActionResult]:
        return [self._complete_document(document_id) for document_id in document_ids]

    def reject_documents(self, document_ids: list[UUID]) -> list[AdminPartnerWebhookActionResult]:
        return [self._reject_document(document_id) for document_id in document_ids]

    def preview_document(self, document_id: UUID) -> list[AdminPartnerWebhookActionResult]:
        document = self.documents.get(document_id)
        skipped = self._skipped_result(document_id, document)
        if skipped is not None:
            return [skipped]

        completed_body, completed_signature, _ = self._build_completed_webhook_request(document.external_job_id)
        rejected_body, rejected_signature = self._build_rejected_webhook_request(document.external_job_id)
        return [
            AdminPartnerWebhookActionResult(
                document_id=document.id,
                filename=document.original_filename,
                status="completed",
                message="Preview only. No database transition was applied.",
                job_id=document.external_job_id,
                request_body=completed_body,
                signature=completed_signature,
            ),
            AdminPartnerWebhookActionResult(
                document_id=document.id,
                filename=document.original_filename,
                status="rejected",
                message="Preview only. No database transition was applied.",
                job_id=document.external_job_id,
                request_body=rejected_body,
                signature=rejected_signature,
            ),
        ]

    def _complete_document(self, document_id: UUID) -> AdminPartnerWebhookActionResult:
        document = self.documents.get(document_id)
        skipped = self._skipped_result(document_id, document)
        if skipped is not None:
            return skipped

        request_body, signature, result = self._build_completed_webhook_request(document.external_job_id)
        if document.status is DocumentStatus.READY:
            message = "Document was already ready."
        else:
            self.processing.mark_partner_completed(document.id, result)
            message = "Partner webhook completed."

        return AdminPartnerWebhookActionResult(
            document_id=document.id,
            filename=document.original_filename,
            status="completed",
            message=message,
            job_id=document.external_job_id,
            request_body=request_body,
            signature=signature,
        )

    def _reject_document(self, document_id: UUID) -> AdminPartnerWebhookActionResult:
        document = self.documents.get(document_id)
        skipped = self._skipped_result(document_id, document)
        if skipped is not None:
            return skipped

        request_body, signature = self._build_rejected_webhook_request(document.external_job_id)
        self.processing.mark_partner_failed(document.id, "rejected")
        return AdminPartnerWebhookActionResult(
            document_id=document.id,
            filename=document.original_filename,
            status="rejected",
            message="Partner webhook rejected.",
            job_id=document.external_job_id,
            request_body=request_body,
            signature=signature,
        )

    def _skipped_result(self, document_id: UUID, document) -> AdminPartnerWebhookActionResult | None:
        if document is None:
            return AdminPartnerWebhookActionResult(
                document_id=document_id,
                filename="-",
                status="skipped",
                message="Document not found.",
            )
        if document.external_job_id is None:
            return AdminPartnerWebhookActionResult(
                document_id=document.id,
                filename=document.original_filename,
                status="skipped",
                message="Document has no partner job id.",
            )
        return None

    def _build_completed_webhook_request(self, job_id: str) -> tuple[str, str, dict[str, Any]]:
        occurred_at = datetime.now(timezone.utc).isoformat()
        result: dict[str, Any] = {
            "source": "admin",
            "message": "Completed from Flask admin partner webhook action.",
            "indexed_at": occurred_at,
        }
        request_body, signature = self._build_webhook_request(
            job_id=job_id,
            status="completed",
            result=result,
            occurred_at=occurred_at,
        )
        return request_body, signature, result

    def _build_rejected_webhook_request(self, job_id: str) -> tuple[str, str]:
        occurred_at = datetime.now(timezone.utc).isoformat()
        result: dict[str, Any] = {
            "source": "admin",
            "reason": "Document invalidated from Flask admin partner webhook action.",
            "rejected_at": occurred_at,
        }
        return self._build_webhook_request(
            job_id=job_id,
            status="rejected",
            result=result,
            occurred_at=occurred_at,
        )

    def _build_webhook_request(
        self,
        *,
        job_id: str,
        status: str,
        result: dict[str, Any],
        occurred_at: str,
    ) -> tuple[str, str]:
        payload = {
            "job_id": job_id,
            "status": status,
            "result": result,
            "occurred_at": occurred_at,
        }
        request_body = json.dumps(payload, separators=(",", ":"))
        signature = build_partner_signature(request_body.encode(), self.hmac_secret)
        return request_body, signature
