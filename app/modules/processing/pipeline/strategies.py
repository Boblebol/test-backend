from enum import StrEnum
from typing import Protocol

from celery import chain, group

from app.modules.processing.chunking.task.chunking import chunk_document
from app.modules.processing.external_call.task.external_call import call_external_partner
from app.modules.processing.initialization.task.process_document import process_document
from app.modules.processing.metadata.task.metadata import extract_metadata
from app.modules.processing.ocr.task.ocr import ocr_document


class PipelineStrategyName(StrEnum):
    ALL = "all"
    OCR = "ocr"
    POST_OCR = "post_ocr"
    METADATA = "metadata"
    CHUNKING = "chunking"
    EXTERNAL_CALL = "external_call"


class UnknownPipelineStrategy(ValueError):
    pass


class PipelineStrategy(Protocol):
    name: PipelineStrategyName

    def build(self, document_id: str):
        pass


class AllPipelineStrategy:
    name = PipelineStrategyName.ALL

    def build(self, document_id: str):
        return chain(
            process_document.si(document_id),
            ocr_document.si(document_id),
            group(
                extract_metadata.si(document_id),
                chunk_document.si(document_id),
            ),
            call_external_partner.si(document_id),
        )


class OcrPipelineStrategy:
    name = PipelineStrategyName.OCR

    def build(self, document_id: str):
        return chain(
            ocr_document.si(document_id),
            group(
                extract_metadata.si(document_id),
                chunk_document.si(document_id),
            ),
            call_external_partner.si(document_id),
        )


class PostOcrPipelineStrategy:
    name = PipelineStrategyName.POST_OCR

    def build(self, document_id: str):
        return chain(
            group(
                extract_metadata.si(document_id),
                chunk_document.si(document_id),
            ),
            call_external_partner.si(document_id),
        )


class MetadataPipelineStrategy:
    name = PipelineStrategyName.METADATA

    def build(self, document_id: str):
        return chain(
            extract_metadata.si(document_id),
            call_external_partner.si(document_id),
        )


class ChunkingPipelineStrategy:
    name = PipelineStrategyName.CHUNKING

    def build(self, document_id: str):
        return chain(
            chunk_document.si(document_id),
            call_external_partner.si(document_id),
        )


class ExternalCallPipelineStrategy:
    name = PipelineStrategyName.EXTERNAL_CALL

    def build(self, document_id: str):
        return call_external_partner.si(document_id)


DEFAULT_PIPELINE_STRATEGIES: dict[PipelineStrategyName, PipelineStrategy] = {
    strategy.name: strategy
    for strategy in (
        AllPipelineStrategy(),
        OcrPipelineStrategy(),
        PostOcrPipelineStrategy(),
        MetadataPipelineStrategy(),
        ChunkingPipelineStrategy(),
        ExternalCallPipelineStrategy(),
    )
}


def resolve_pipeline_strategy(
    strategy: PipelineStrategyName | str | None = None,
    *,
    strategies: dict[PipelineStrategyName, PipelineStrategy] | None = None,
) -> PipelineStrategy:
    strategy_name = _resolve_strategy_name(strategy)
    registry = strategies or DEFAULT_PIPELINE_STRATEGIES
    try:
        return registry[strategy_name]
    except KeyError as exc:
        raise UnknownPipelineStrategy(f"Unknown pipeline strategy: {strategy_name}") from exc


def build_full_pipeline_workflow(document_id: str):
    return resolve_pipeline_strategy(PipelineStrategyName.ALL).build(document_id)


def _resolve_strategy_name(strategy: PipelineStrategyName | str | None) -> PipelineStrategyName:
    if strategy is None:
        return PipelineStrategyName.ALL
    if isinstance(strategy, PipelineStrategyName):
        return strategy
    try:
        return PipelineStrategyName(strategy)
    except ValueError as exc:
        raise UnknownPipelineStrategy(f"Unknown pipeline strategy: {strategy}") from exc
