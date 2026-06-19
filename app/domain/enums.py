from enum import StrEnum


class DocumentStatus(StrEnum):
    WAITING_UPLOAD = "waiting_upload"
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    WAITING_PARTNER = "waiting_partner"
    READY = "ready"
    FAILED = "failed"


class ProcessingStepName(StrEnum):
    OCR = "ocr"
    METADATA = "metadata"
    CHUNKING = "chunking"
    EXTERNAL_CALL = "external_call"
    PARTNER_WEBHOOK = "partner_webhook"


class ProcessingStepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    RETRYING = "retrying"
    SUCCESS = "success"
    WAITING_WEBHOOK = "waiting_webhook"
    FAILED = "failed"
    SKIPPED = "skipped"
