from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db_session
from app.domain.enums import DocumentStatus
from app.modules.documents.repository import DocumentRepository
from app.modules.processing.result_repository import ExtractedDataRepository
from app.modules.processing.step_repository import ProcessingStepRepository
from app.modules.partner_webhooks.signatures import is_valid_partner_signature
from app.modules.processing.service import ProcessingService
from app.modules.processing.progress import (
    CollectingProgressPublisher,
    ProgressPublisher,
    build_redis_progress_publisher,
    publish_collected_events,
)


router = APIRouter(prefix="/webhooks", tags=["Partner webhook"])


class PartnerWebhookPayload(BaseModel):
    job_id: str = Field(description="External partner job id returned by the pipeline.")
    status: str = Field(description="Partner status. `completed` marks the document ready.")
    result: dict[str, Any] = Field(description="Partner result payload stored on the document.")
    occurred_at: datetime = Field(description="Partner event timestamp.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "job_id": "j_abc123def4567890",
                "status": "completed",
                "result": {"indexed_at": "2026-05-21T14:23:11Z"},
                "occurred_at": "2026-05-21T14:23:11Z",
            }
        }
    }


class PartnerWebhookResponse(BaseModel):
    document_id: UUID
    status: DocumentStatus


PARTNER_WEBHOOK_REQUEST_BODY = {
    "required": True,
    "content": {
        "application/json": {
            "schema": PartnerWebhookPayload.model_json_schema(),
            "example": PartnerWebhookPayload.model_config["json_schema_extra"]["example"],
        }
    },
}


def get_progress_publisher() -> ProgressPublisher:
    return build_redis_progress_publisher(get_settings().redis_url)


@router.post(
    "/partner",
    response_model=PartnerWebhookResponse,
    summary="Receive partner result",
    description=(
        "Validate `X-Partner-Signature` against the raw request body, then mark the matching "
        "document ready or failed from the partner job id."
    ),
    openapi_extra={"requestBody": PARTNER_WEBHOOK_REQUEST_BODY},
)
async def partner_webhook(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    progress_publisher: Annotated[ProgressPublisher, Depends(get_progress_publisher)],
    x_partner_signature: Annotated[
        str | None,
        Header(
            alias="X-Partner-Signature",
            description="HMAC-SHA256 hex digest computed from the exact raw request body.",
        ),
    ] = None,
) -> PartnerWebhookResponse:
    raw_body = await request.body()
    settings = get_settings()
    if x_partner_signature is None or not is_valid_partner_signature(
        raw_body,
        x_partner_signature,
        settings.partner_hmac_secret,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid partner signature",
        )

    try:
        payload = PartnerWebhookPayload.model_validate_json(raw_body)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors()) from exc

    documents = DocumentRepository(session)
    document = documents.get_by_external_job_id(payload.job_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Partner job not found")
    if document.status is DocumentStatus.READY:
        return PartnerWebhookResponse(document_id=document.id, status=DocumentStatus.READY)

    collected_progress = CollectingProgressPublisher()
    processing = ProcessingService(
        documents=documents,
        steps=ProcessingStepRepository(session),
        extracted_data=ExtractedDataRepository(session),
        publisher=collected_progress,
    )
    if payload.status == "completed":
        processing.mark_partner_completed(document.id, payload.result)
        response_status = DocumentStatus.READY
    else:
        processing.mark_partner_failed(document.id, payload.status)
        response_status = DocumentStatus.FAILED

    session.commit()
    publish_collected_events(collected_progress, progress_publisher)
    return PartnerWebhookResponse(document_id=document.id, status=response_status)
