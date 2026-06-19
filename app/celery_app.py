from celery import Celery

from app.core.config import get_settings


def create_celery_app() -> Celery:
    settings = get_settings()
    celery = Celery(
        "primmo",
        broker=settings.redis_url,
        backend=settings.redis_url,
        include=[
            "app.modules.processing.initialization.task.process_document",
            "app.modules.processing.ocr.task.ocr",
            "app.modules.processing.metadata.task.metadata",
            "app.modules.processing.chunking.task.chunking",
            "app.modules.processing.external_call.task.external_call",
            "app.modules.processing.recovery.task.recover_uploaded",
        ],
    )
    celery.conf.update(
        task_default_queue="documents.pipeline",
        task_routes={
            "app.modules.processing.initialization.task.process_document.process_document": {
                "queue": "documents.pipeline"
            },
            "app.modules.processing.ocr.task.ocr.ocr_document": {"queue": "documents.ocr"},
            "app.modules.processing.metadata.task.metadata.extract_metadata": {
                "queue": "documents.metadata"
            },
            "app.modules.processing.chunking.task.chunking.chunk_document": {
                "queue": "documents.chunking"
            },
            "app.modules.processing.external_call.task.external_call.call_external_partner": {
                "queue": "documents.external_call"
            },
            "app.modules.processing.recovery.task.recover_uploaded.recover_stale_uploaded_documents_task": {
                "queue": "documents.recovery"
            },
        },
        beat_schedule={
            "recover-stale-uploaded-documents": {
                "task": (
                    "app.modules.processing.recovery.task.recover_uploaded."
                    "recover_stale_uploaded_documents_task"
                ),
                "schedule": 60 * 60,
                "kwargs": {"stale_after_hours": 24, "limit": 100},
                "options": {"queue": "documents.recovery"},
            }
        },
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
    )
    return celery


celery_app = create_celery_app()
