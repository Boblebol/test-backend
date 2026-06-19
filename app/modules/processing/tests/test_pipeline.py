from uuid import uuid4

import pytest

from app.modules.processing.pipeline import (
    PipelineOrchestrator,
    PipelineStrategyName,
    UnknownPipelineStrategy,
    resolve_pipeline_strategy,
)


PROCESS_DOCUMENT = "app.modules.processing.initialization.task.process_document.process_document"
OCR = "app.modules.processing.ocr.task.ocr.ocr_document"
METADATA = "app.modules.processing.metadata.task.metadata.extract_metadata"
CHUNKING = "app.modules.processing.chunking.task.chunking.chunk_document"
EXTERNAL_CALL = "app.modules.processing.external_call.task.external_call.call_external_partner"


def test_resolve_pipeline_strategy_defaults_to_full_pipeline() -> None:
    strategy = resolve_pipeline_strategy()

    assert strategy.name is PipelineStrategyName.ALL


@pytest.mark.parametrize(
    ("name", "expected_canvas"),
    [
        (
            "all",
            [
                PROCESS_DOCUMENT,
                OCR,
                {"group": [METADATA, CHUNKING], "then": EXTERNAL_CALL},
            ],
        ),
        (
            "ocr",
            [
                OCR,
                {"group": [METADATA, CHUNKING], "then": EXTERNAL_CALL},
            ],
        ),
        (
            "post_ocr",
            {"group": [METADATA, CHUNKING], "then": EXTERNAL_CALL},
        ),
        (
            "metadata",
            [METADATA, EXTERNAL_CALL],
        ),
        (
            "chunking",
            [CHUNKING, EXTERNAL_CALL],
        ),
        (
            "external_call",
            EXTERNAL_CALL,
        ),
    ],
)
def test_pipeline_strategies_build_expected_dependency_chain(
    name: str,
    expected_canvas,
) -> None:
    workflow = resolve_pipeline_strategy(name).build("document-id")

    assert describe_canvas(workflow) == expected_canvas


def test_resolve_pipeline_strategy_rejects_unknown_strategy() -> None:
    with pytest.raises(UnknownPipelineStrategy, match="Unknown pipeline strategy"):
        resolve_pipeline_strategy("missing")


def test_pipeline_orchestrator_enqueues_resolved_strategy() -> None:
    document_id = uuid4()
    strategy = RecordingStrategy()
    orchestrator = PipelineOrchestrator(strategies={PipelineStrategyName.METADATA: strategy})

    task_id = orchestrator.enqueue(document_id, strategy="metadata")

    assert task_id == "task-123"
    assert strategy.document_ids == [str(document_id)]
    assert strategy.workflow.applied is True


def test_pipeline_orchestrator_keeps_full_pipeline_shortcut() -> None:
    document_id = uuid4()
    strategy = RecordingStrategy(name=PipelineStrategyName.ALL)
    orchestrator = PipelineOrchestrator(strategies={PipelineStrategyName.ALL: strategy})

    task_id = orchestrator.enqueue_full_pipeline(document_id)

    assert task_id == "task-123"
    assert strategy.document_ids == [str(document_id)]


class RecordingStrategy:
    def __init__(self, name: PipelineStrategyName = PipelineStrategyName.METADATA) -> None:
        self.name = name
        self.workflow = RecordingWorkflow()
        self.document_ids: list[str] = []

    def build(self, document_id: str):
        self.document_ids.append(document_id)
        return self.workflow


class RecordingWorkflow:
    def __init__(self) -> None:
        self.applied = False

    def apply_async(self):
        self.applied = True
        return RecordingAsyncResult()


class RecordingAsyncResult:
    id = "task-123"


def describe_canvas(canvas):
    if getattr(canvas, "body", None) is not None:
        return {
            "group": [describe_canvas(task) for task in canvas.tasks],
            "then": describe_canvas(canvas.body),
        }
    if getattr(canvas, "tasks", None) is not None:
        return [describe_canvas(task) for task in canvas.tasks]
    assert canvas.args == ("document-id",)
    return canvas.task
