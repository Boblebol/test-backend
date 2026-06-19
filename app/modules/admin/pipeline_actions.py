from dataclasses import dataclass, replace
from uuid import UUID

from sqlalchemy.orm import Session

from app.domain.enums import DocumentStatus, ProcessingStepName, ProcessingStepStatus
from app.modules.documents.repository import DocumentRepository
from app.modules.processing.pipeline import PipelineStrategyName, resolve_pipeline_strategy
from app.modules.processing.result_repository import ExtractedDataRepository
from app.modules.processing.step_repository import ProcessingStepRepository


@dataclass(frozen=True)
class AdminPipelineActionResult:
    document_id: UUID
    filename: str
    strategy: PipelineStrategyName
    status: str
    message: str
    task_id: str | None = None


@dataclass(frozen=True)
class PipelineResetPlan:
    steps: tuple[ProcessingStepName, ...]
    clear_ocr: bool = False
    clear_metadata: bool = False
    clear_chunks: bool = False
    clear_partner: bool = False
    require_ocr: bool = False
    require_metadata: bool = False
    require_chunks: bool = False


PIPELINE_RESET_PLANS: dict[PipelineStrategyName, PipelineResetPlan] = {
    PipelineStrategyName.ALL: PipelineResetPlan(
        steps=tuple(ProcessingStepName),
        clear_ocr=True,
        clear_metadata=True,
        clear_chunks=True,
        clear_partner=True,
    ),
    PipelineStrategyName.OCR: PipelineResetPlan(
        steps=(
            ProcessingStepName.OCR,
            ProcessingStepName.METADATA,
            ProcessingStepName.CHUNKING,
            ProcessingStepName.EXTERNAL_CALL,
            ProcessingStepName.PARTNER_WEBHOOK,
        ),
        clear_ocr=True,
        clear_metadata=True,
        clear_chunks=True,
        clear_partner=True,
    ),
    PipelineStrategyName.POST_OCR: PipelineResetPlan(
        steps=(
            ProcessingStepName.METADATA,
            ProcessingStepName.CHUNKING,
            ProcessingStepName.EXTERNAL_CALL,
            ProcessingStepName.PARTNER_WEBHOOK,
        ),
        clear_metadata=True,
        clear_chunks=True,
        clear_partner=True,
        require_ocr=True,
    ),
    PipelineStrategyName.METADATA: PipelineResetPlan(
        steps=(
            ProcessingStepName.METADATA,
            ProcessingStepName.EXTERNAL_CALL,
            ProcessingStepName.PARTNER_WEBHOOK,
        ),
        clear_metadata=True,
        clear_partner=True,
        require_ocr=True,
        require_chunks=True,
    ),
    PipelineStrategyName.CHUNKING: PipelineResetPlan(
        steps=(
            ProcessingStepName.CHUNKING,
            ProcessingStepName.EXTERNAL_CALL,
            ProcessingStepName.PARTNER_WEBHOOK,
        ),
        clear_chunks=True,
        clear_partner=True,
        require_ocr=True,
        require_metadata=True,
    ),
    PipelineStrategyName.EXTERNAL_CALL: PipelineResetPlan(
        steps=(
            ProcessingStepName.EXTERNAL_CALL,
            ProcessingStepName.PARTNER_WEBHOOK,
        ),
        clear_partner=True,
        require_ocr=True,
        require_metadata=True,
        require_chunks=True,
    ),
}


class AdminPipelineActions:
    def __init__(self, session: Session):
        self.documents = DocumentRepository(session)
        self.steps = ProcessingStepRepository(session)
        self.extracted_data = ExtractedDataRepository(session)

    def prepare_documents(
        self,
        document_ids: list[UUID],
        strategy: PipelineStrategyName | str,
    ) -> list[AdminPipelineActionResult]:
        resolved_strategy = resolve_pipeline_strategy(strategy).name
        return [self._prepare_document(document_id, resolved_strategy) for document_id in document_ids]

    @staticmethod
    def mark_queued(
        result: AdminPipelineActionResult,
        *,
        task_id: str,
    ) -> AdminPipelineActionResult:
        return replace(result, status="queued", message="Pipeline queued.", task_id=task_id)

    @staticmethod
    def mark_enqueue_failed(
        result: AdminPipelineActionResult,
        *,
        error: Exception,
    ) -> AdminPipelineActionResult:
        return replace(
            result,
            status="error",
            message=f"Pipeline enqueue failed: {type(error).__name__}",
        )

    def _prepare_document(
        self,
        document_id: UUID,
        strategy: PipelineStrategyName,
    ) -> AdminPipelineActionResult:
        document = self.documents.get(document_id)
        if document is None:
            return AdminPipelineActionResult(
                document_id=document_id,
                filename="-",
                strategy=strategy,
                status="skipped",
                message="Document not found.",
            )
        if document.status is DocumentStatus.WAITING_UPLOAD:
            return AdminPipelineActionResult(
                document_id=document.id,
                filename=document.original_filename,
                strategy=strategy,
                status="skipped",
                message="Document has not been uploaded yet.",
            )

        plan = PIPELINE_RESET_PLANS[strategy]
        missing = self._missing_requirements(document.id, plan)
        if missing:
            return AdminPipelineActionResult(
                document_id=document.id,
                filename=document.original_filename,
                strategy=strategy,
                status="skipped",
                message=f"Missing required output: {', '.join(missing)}.",
            )

        self.extracted_data.create_empty(document.id)
        self.extracted_data.clear_outputs(
            document.id,
            ocr=plan.clear_ocr,
            metadata=plan.clear_metadata,
            chunks=plan.clear_chunks,
            partner=plan.clear_partner,
        )
        self.documents.clear_external_job(document.id)
        self.documents.update_status(document.id, DocumentStatus.PROCESSING)
        for step in plan.steps:
            self.steps.upsert(
                document_id=document.id,
                name=step,
                status=ProcessingStepStatus.PENDING,
                updated_by="admin-rerun",
            )

        return AdminPipelineActionResult(
            document_id=document.id,
            filename=document.original_filename,
            strategy=strategy,
            status="prepared",
            message="Pipeline state reset.",
        )

    def _missing_requirements(
        self,
        document_id: UUID,
        plan: PipelineResetPlan,
    ) -> list[str]:
        extracted = self.extracted_data.get(document_id)
        missing: list[str] = []
        if plan.require_ocr and (extracted is None or extracted.ocr_text is None):
            missing.append("ocr")
        if plan.require_metadata and (extracted is None or extracted.metadata_json is None):
            missing.append("metadata")
        if plan.require_chunks and (extracted is None or extracted.chunks_json is None):
            missing.append("chunks")
        return missing
