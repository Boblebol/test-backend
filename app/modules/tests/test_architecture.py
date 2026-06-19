from app.modules.auth import routes as auth_routes
from app.modules.documents import routes as document_routes
from app.modules.partner_webhooks import routes as webhook_routes
from app.modules.processing.chunking.chunking import chunking
from app.modules.processing.chunking.task.chunking import chunk_document
from app.modules.processing.external_call.external_call import external_call
from app.modules.processing.external_call.task.external_call import call_external_partner
from app.modules.processing.metadata.metadata import metadata
from app.modules.processing.metadata.task.metadata import extract_metadata
from app.modules.processing.ocr.ocr import ocr
from app.modules.processing.ocr.task.ocr import ocr_document
from app.modules.processing.pipeline import PipelineOrchestrator, resolve_pipeline_strategy
from app.modules.processing.initialization.task.process_document import process_document


def test_vertical_modules_expose_entrypoints() -> None:
    assert auth_routes.router.prefix == "/auth"
    assert document_routes.router.prefix == "/documents"
    assert webhook_routes.router.prefix == "/webhooks"
    assert PipelineOrchestrator is not None
    assert resolve_pipeline_strategy().name == "all"


def test_each_celery_task_lives_in_its_own_file() -> None:
    assert process_document.run.__module__ == "app.modules.processing.initialization.task.process_document"
    assert ocr_document.run.__module__ == "app.modules.processing.ocr.task.ocr"
    assert extract_metadata.run.__module__ == "app.modules.processing.metadata.task.metadata"
    assert chunk_document.run.__module__ == "app.modules.processing.chunking.task.chunking"
    assert call_external_partner.run.__module__ == "app.modules.processing.external_call.task.external_call"


def test_processing_step_function_lives_next_to_its_task() -> None:
    assert ocr.__module__ == "app.modules.processing.ocr.ocr"
    assert metadata.__module__ == "app.modules.processing.metadata.metadata"
    assert chunking.__module__ == "app.modules.processing.chunking.chunking"
    assert external_call.__module__ == "app.modules.processing.external_call.external_call"
