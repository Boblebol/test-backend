import base64
import binascii
import json
from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse

from app.modules.auth.dependencies import get_current_user
from app.core.config import get_settings
from app.db.session import get_db_session
from app.domain.enums import DocumentStatus, ProcessingStepName, ProcessingStepStatus
from app.domain.models import (
    CreateDocumentCommand,
    DocumentState,
    ExtractedDataState,
    ProcessingStepState,
    UploadUrlState,
    UserState,
)
from app.modules.documents.repository import DocumentRepository
from app.modules.organizations.repository import OrganizationRepository
from app.modules.processing.result_repository import ExtractedDataRepository
from app.modules.processing.step_repository import ProcessingStepRepository
from app.modules.documents.service import (
    DocumentService,
    DocumentUploadNotPending,
    DocumentUploadService,
    InvalidDocumentUpload,
    UploadedFileMissing,
)
from app.modules.processing.pipeline import PipelineOrchestrator
from app.modules.processing.progress import (
    ProgressSubscriber,
    build_redis_progress_subscriber,
    progress_channel,
)
from app.modules.documents.storage import ObjectStorageUnavailable, S3ObjectStorage


router = APIRouter(prefix="/documents", tags=["Documents"])


class CreateDocumentRequest(BaseModel):
    filename: str = Field(description="Original PDF filename.")
    content_type: str = Field(description="Expected content type. Only `application/pdf` is accepted.")
    size_bytes: int = Field(description="Expected file size in bytes.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "filename": "lease.pdf",
                "content_type": "application/pdf",
                "size_bytes": 1024,
            }
        }
    }


class DocumentResponse(BaseModel):
    id: UUID
    org_id: UUID
    owner_user_id: UUID
    original_filename: str
    content_type: str
    size_bytes: int
    storage_bucket: str
    storage_key: str
    status: DocumentStatus
    external_job_id: str | None
    current_error_type: str | None
    current_error_message: str | None
    created_at: datetime | None
    updated_at: datetime | None
    pipeline_steps: dict[ProcessingStepName, ProcessingStepStatus] = Field(
        default_factory=dict,
        description="Current status by pipeline step when available.",
    )


class DocumentResultResponse(BaseModel):
    document_id: UUID
    ocr_text: str | None
    metadata_json: dict[str, Any] | None
    chunks_json: list[str] | None
    partner_result_json: dict[str, Any] | None


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    next_cursor: str | None

    model_config = {
        "json_schema_extra": {
            "example": {
                "items": [],
                "next_cursor": None,
            }
        }
    }


class UploadUrlResponse(BaseModel):
    document_id: UUID
    upload_url: str
    upload_method: str
    expires_in_seconds: int
    upload_headers: dict[str, str]


class CreateDocumentResponse(DocumentResponse):
    document_id: UUID
    upload_url: str
    upload_method: str
    expires_in_seconds: int
    upload_headers: dict[str, str]


def get_object_storage() -> S3ObjectStorage:
    settings = get_settings()
    return S3ObjectStorage(
        endpoint=settings.minio_endpoint,
        public_endpoint=settings.minio_public_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        region=settings.minio_region,
    )


def get_pipeline_orchestrator() -> PipelineOrchestrator:
    return PipelineOrchestrator()


def get_progress_subscriber() -> ProgressSubscriber:
    return build_redis_progress_subscriber(get_settings().redis_url)


@router.post(
    "",
    response_model=CreateDocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a document upload",
    description=(
        "Create a tenant-scoped document in `waiting_upload`. "
        "Use the returned upload_url to PUT the PDF, then call complete-upload."
    ),
    response_description="Document metadata and presigned upload instructions.",
)
def create_document(
    body: CreateDocumentRequest,
    current_user: Annotated[UserState, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    storage: Annotated[S3ObjectStorage, Depends(get_object_storage)],
) -> CreateDocumentResponse:
    settings = get_settings()
    documents = DocumentRepository(session)
    organization = OrganizationRepository(session).get(current_user.org_id)
    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Current user organization not found",
        )
    service = DocumentService(
        documents=documents,
        storage_bucket=settings.minio_bucket,
        max_upload_size_bytes=settings.max_upload_size_bytes,
    )
    upload_service = DocumentUploadService(
        documents=documents,
        storage=storage,
        upload_url_expires_seconds=settings.upload_url_expires_seconds,
    )

    try:
        document = service.create_document(
            CreateDocumentCommand(
                org_id=current_user.org_id,
                org_name=organization.name,
                owner_user_id=current_user.id,
                owner_user_email=current_user.email,
                filename=body.filename,
                content_type=body.content_type,
                size_bytes=body.size_bytes,
            )
        )
    except InvalidDocumentUpload as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    upload = upload_service.create_upload_url(document)
    session.commit()
    return _create_document_response(document, upload)


@router.get(
    "",
    response_model=DocumentListResponse,
    summary="List tenant documents",
    description=(
        "Return the current user's organization documents. "
        "Use `limit` and the opaque `next_cursor` value for cursor pagination."
    ),
)
def list_documents(
    current_user: Annotated[UserState, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=100, description="Page size, from 1 to 100.")] = 50,
    cursor: Annotated[str | None, Query(description="Opaque cursor returned by `next_cursor`.")] = None,
    status_filter: Annotated[
        DocumentStatus | None,
        Query(alias="status", description="Optional document status filter."),
    ] = None,
    owner_user_id: Annotated[UUID | None, Query(description="Optional owner user filter.")] = None,
    created_from: Annotated[datetime | None, Query(description="Inclusive lower bound on created_at.")] = None,
    created_to: Annotated[datetime | None, Query(description="Inclusive upper bound on created_at.")] = None,
) -> DocumentListResponse:
    documents = DocumentRepository(session).list_for_org_page(
        org_id=current_user.org_id,
        limit=limit + 1,
        status=status_filter,
        owner_user_id=owner_user_id,
        created_from=created_from,
        created_to=created_to,
        cursor=_decode_documents_cursor(cursor) if cursor is not None else None,
    )
    page = documents[:limit]
    next_cursor = None
    if len(documents) > limit and page:
        last = page[-1]
        if last.created_at is not None:
            next_cursor = _encode_documents_cursor(last.created_at, last.id)
    return DocumentListResponse(
        items=[_document_response(document) for document in page],
        next_cursor=next_cursor,
    )


@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
    summary="Get document status",
    description="Return a tenant-scoped document with its current processing status.",
)
def get_document(
    document_id: UUID,
    current_user: Annotated[UserState, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> DocumentResponse:
    document = _get_document_for_current_org(session, document_id, current_user.org_id)
    steps = ProcessingStepRepository(session).list_for_document(document.id)
    return _document_response(document, steps)


@router.get(
    "/{document_id}/upload-url",
    response_model=UploadUrlResponse,
    summary="Regenerate upload URL",
    description="Return a fresh presigned PUT URL while the document is still waiting for upload.",
)
def get_document_upload_url(
    document_id: UUID,
    current_user: Annotated[UserState, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    storage: Annotated[S3ObjectStorage, Depends(get_object_storage)],
) -> UploadUrlResponse:
    document = _get_document_for_current_org(session, document_id, current_user.org_id)
    upload_service = DocumentUploadService(
        documents=DocumentRepository(session),
        storage=storage,
        upload_url_expires_seconds=get_settings().upload_url_expires_seconds,
    )

    try:
        upload = upload_service.create_upload_url(document)
    except DocumentUploadNotPending as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _upload_response(upload)


@router.post(
    "/{document_id}/complete-upload",
    response_model=DocumentResponse,
    summary="Complete upload and start processing",
    description="Verify that the PDF exists in storage, mark the document uploaded and enqueue the pipeline.",
)
def complete_document_upload(
    document_id: UUID,
    current_user: Annotated[UserState, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    storage: Annotated[S3ObjectStorage, Depends(get_object_storage)],
    pipeline: Annotated[PipelineOrchestrator, Depends(get_pipeline_orchestrator)],
) -> DocumentResponse:
    documents = DocumentRepository(session)
    document = _get_document_for_current_org(session, document_id, current_user.org_id)
    upload_service = DocumentUploadService(
        documents=documents,
        storage=storage,
        upload_url_expires_seconds=get_settings().upload_url_expires_seconds,
    )

    try:
        updated = upload_service.complete_upload(document)
    except DocumentUploadNotPending as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except UploadedFileMissing as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ObjectStorageUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    session.commit()
    pipeline.enqueue_full_pipeline(updated.id)
    return _document_response(updated)


@router.get(
    "/{document_id}/result",
    response_model=DocumentResultResponse,
    summary="Read extracted result",
    description="Return extracted data only once the document is `ready`; otherwise returns 409.",
    responses={
        status.HTTP_409_CONFLICT: {
            "description": "Document result is not ready yet",
            "content": {
                "application/json": {
                    "example": {
                        "detail": {
                            "message": "Document result is not ready",
                            "document_id": "00000000-0000-0000-0000-000000000000",
                            "status": "processing",
                        }
                    }
                }
            },
        }
    },
)
def get_document_result(
    document_id: UUID,
    current_user: Annotated[UserState, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> DocumentResultResponse:
    document = _get_document_for_current_org(session, document_id, current_user.org_id)
    if document.status is not DocumentStatus.READY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Document result is not ready",
                "document_id": str(document.id),
                "status": document.status.value,
            },
        )
    result = ExtractedDataRepository(session).get(document.id)
    return _result_response(document.id, result)


@router.get(
    "/{document_id}/events",
    summary="Stream document progress",
    description="Server-sent events stream with an initial snapshot and later processing progress events.",
)
def stream_document_events(
    document_id: UUID,
    current_user: Annotated[UserState, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    subscriber: Annotated[ProgressSubscriber, Depends(get_progress_subscriber)],
) -> StreamingResponse:
    document = _get_document_for_current_org(session, document_id, current_user.org_id)
    return StreamingResponse(
        _document_event_stream(document, subscriber),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _get_document_for_current_org(
    session: Session,
    document_id: UUID,
    org_id: UUID,
) -> DocumentState:
    document = DocumentRepository(session).get_for_org(document_id, org_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return document


def _encode_documents_cursor(created_at: datetime, document_id: UUID) -> str:
    payload = {
        "created_at": created_at.astimezone(timezone.utc).isoformat(),
        "id": str(document_id),
    }
    return base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()


def _decode_documents_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        return datetime.fromisoformat(payload["created_at"]), UUID(payload["id"])
    except (
        binascii.Error,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        UnicodeDecodeError,
        ValueError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid pagination cursor") from exc


def _document_response(
    document: DocumentState,
    steps: list[ProcessingStepState] | None = None,
) -> DocumentResponse:
    return DocumentResponse(
        id=document.id,
        org_id=document.org_id,
        owner_user_id=document.owner_user_id,
        original_filename=document.original_filename,
        content_type=document.content_type,
        size_bytes=document.size_bytes,
        storage_bucket=document.storage_bucket,
        storage_key=document.storage_key,
        status=document.status,
        external_job_id=document.external_job_id,
        current_error_type=document.current_error_type,
        current_error_message=document.current_error_message,
        created_at=document.created_at,
        updated_at=document.updated_at,
        pipeline_steps={step.name: step.status for step in steps or []},
    )


def _create_document_response(
    document: DocumentState,
    upload: UploadUrlState,
) -> CreateDocumentResponse:
    document_response = _document_response(document)
    return CreateDocumentResponse(
        **document_response.model_dump(),
        document_id=upload.document_id,
        upload_url=upload.upload_url,
        upload_method=upload.upload_method,
        expires_in_seconds=upload.expires_in_seconds,
        upload_headers=upload.upload_headers,
    )


def _upload_response(upload: UploadUrlState) -> UploadUrlResponse:
    return UploadUrlResponse(
        document_id=upload.document_id,
        upload_url=upload.upload_url,
        upload_method=upload.upload_method,
        expires_in_seconds=upload.expires_in_seconds,
        upload_headers=upload.upload_headers,
    )


def _result_response(
    document_id: UUID,
    result: ExtractedDataState | None,
) -> DocumentResultResponse:
    if result is None:
        return DocumentResultResponse(
            document_id=document_id,
            ocr_text=None,
            metadata_json=None,
            chunks_json=None,
            partner_result_json=None,
        )

    return DocumentResultResponse(
        document_id=result.document_id,
        ocr_text=result.ocr_text,
        metadata_json=result.metadata_json,
        chunks_json=result.chunks_json,
        partner_result_json=result.partner_result_json,
    )


def _document_event_stream(document: DocumentState, subscriber: ProgressSubscriber):
    channel = progress_channel(document.org_id, document.id)
    yield _sse(
        "snapshot",
        {
            "org_id": str(document.org_id),
            "document_id": str(document.id),
            "document_status": document.status.value,
            "occurred_at": _event_timestamp(document),
        },
    )

    subscriber.subscribe(channel)
    try:
        while True:
            try:
                payload = subscriber.next_message(timeout_seconds=15)
            except StopIteration:
                break
            if payload is None:
                yield ": keep-alive\n\n"
            else:
                yield f"event: progress\ndata: {payload}\n\n"
    finally:
        subscriber.close()


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"


def _event_timestamp(document: DocumentState) -> str:
    occurred_at = document.updated_at or datetime.now(timezone.utc)
    return occurred_at.isoformat()
