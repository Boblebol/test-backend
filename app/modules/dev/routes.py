from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.modules.auth.dependencies import get_current_user
from app.core.config import get_settings
from app.db.session import get_db_session
from app.domain.models import UserState
from app.modules.documents.repository import DocumentRepository
from app.modules.partner_webhooks.signatures import build_partner_signature
from app.modules.documents.storage import ObjectStorageUnavailable, S3ObjectStorage


router = APIRouter(prefix="/dev", tags=["Local test helpers"])


class PartnerSignatureRequest(BaseModel):
    body: str

    model_config = {
        "json_schema_extra": {
            "example": {
                "body": (
                    '{"job_id":"j_abc123def4567890","status":"completed",'
                    '"result":{"indexed_at":"2026-05-21T14:23:11Z"},'
                    '"occurred_at":"2026-05-21T14:23:11Z"}'
                )
            }
        }
    }


class PartnerSignatureResponse(BaseModel):
    signature: str


class DevUploadResponse(BaseModel):
    document_id: UUID
    storage_bucket: str
    storage_key: str
    content_type: str
    size_bytes: int


def get_dev_object_storage() -> S3ObjectStorage:
    settings = get_settings()
    return S3ObjectStorage(
        endpoint=settings.minio_endpoint,
        public_endpoint=settings.minio_public_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        region=settings.minio_region,
    )


def ensure_dev_endpoint_enabled() -> None:
    if get_settings().app_env not in {"local", "test"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


@router.post(
    "/partner-signature",
    response_model=PartnerSignatureResponse,
    summary="TEST ONLY - Build partner webhook signature",
    description="Endpoint local/test uniquement pour aider les essais Swagger.",
    dependencies=[Depends(ensure_dev_endpoint_enabled)],
)
def create_partner_signature(body: PartnerSignatureRequest) -> PartnerSignatureResponse:
    settings = get_settings()
    return PartnerSignatureResponse(
        signature=build_partner_signature(
            body.body.encode(),
            settings.partner_hmac_secret,
        )
    )


@router.post(
    "/documents/{document_id}/upload",
    response_model=DevUploadResponse,
    summary="TEST ONLY - Upload a document file",
    description=(
        "Endpoint de test uniquement, actif seulement en APP_ENV=local/test. "
        "Il depose le PDF dans l'objet MinIO attendu par le document pour faciliter Swagger."
    ),
    dependencies=[Depends(ensure_dev_endpoint_enabled)],
)
async def upload_document_for_test(
    document_id: UUID,
    current_user: Annotated[UserState, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    storage: Annotated[S3ObjectStorage, Depends(get_dev_object_storage)],
    file: Annotated[UploadFile, File(description="Test-only local PDF upload")],
) -> DevUploadResponse:
    if file.content_type != "application/pdf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="only application/pdf uploads are accepted",
        )

    document = DocumentRepository(session).get_for_org(document_id, current_user.org_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    content = await file.read()
    try:
        storage.put_object(
            bucket=document.storage_bucket,
            key=document.storage_key,
            content=content,
            content_type=file.content_type,
        )
    except ObjectStorageUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    return DevUploadResponse(
        document_id=document.id,
        storage_bucket=document.storage_bucket,
        storage_key=document.storage_key,
        content_type=file.content_type,
        size_bytes=len(content),
    )
