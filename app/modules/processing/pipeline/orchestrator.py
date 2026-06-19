from uuid import UUID

from app.modules.processing.pipeline.strategies import (
    DEFAULT_PIPELINE_STRATEGIES,
    PipelineStrategy,
    PipelineStrategyName,
    resolve_pipeline_strategy,
)


class PipelineOrchestrator:
    def __init__(self, strategies: dict[PipelineStrategyName, PipelineStrategy] | None = None):
        self.strategies = strategies or DEFAULT_PIPELINE_STRATEGIES

    def enqueue(
        self,
        document_id: UUID,
        strategy: PipelineStrategyName | str | None = None,
    ) -> str:
        selected_strategy = resolve_pipeline_strategy(strategy, strategies=self.strategies)
        result = selected_strategy.build(str(document_id)).apply_async()
        return result.id

    def enqueue_full_pipeline(self, document_id: UUID) -> str:
        return self.enqueue(document_id, PipelineStrategyName.ALL)
