import uuid
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ProcessingStepORM
from app.domain.enums import ProcessingStepName, ProcessingStepStatus
from app.domain.models import ProcessingStepState
from app.db.mappers import processing_step_to_state


class ProcessingStepRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_for_document(self, document_id: UUID) -> list[ProcessingStepState]:
        rows = self.session.scalars(
            select(ProcessingStepORM)
            .where(ProcessingStepORM.document_id == document_id)
            .order_by(ProcessingStepORM.name)
        ).all()
        return [processing_step_to_state(row) for row in rows]

    def upsert(
        self,
        document_id: UUID,
        name: ProcessingStepName,
        status: ProcessingStepStatus,
        updated_by: str,
    ) -> None:
        row = self.session.scalar(
            select(ProcessingStepORM).where(
                ProcessingStepORM.document_id == document_id,
                ProcessingStepORM.name == name.value,
            )
        )
        if row is None:
            row = ProcessingStepORM(
                id=uuid.uuid4(),
                document_id=document_id,
                name=name.value,
                status=status.value,
                attempt_count=0,
                updated_by=updated_by,
            )
            self.session.add(row)
            return

        row.status = status.value
        row.attempt_count = 0
        row.result_json = None
        row.error_type = None
        row.error_message = None
        row.updated_by = updated_by

    def set_result(
        self,
        document_id: UUID,
        name: ProcessingStepName,
        result_json: dict,
    ) -> None:
        self.session.flush()
        row = self.session.scalar(
            select(ProcessingStepORM).where(
                ProcessingStepORM.document_id == document_id,
                ProcessingStepORM.name == name.value,
            )
        )
        if row is None:
            return
        row.result_json = result_json

    def update_status(
        self,
        document_id: UUID,
        name: ProcessingStepName,
        status: ProcessingStepStatus,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        row = self.session.scalar(
            select(ProcessingStepORM).where(
                ProcessingStepORM.document_id == document_id,
                ProcessingStepORM.name == name.value,
            )
        )
        if row is None:
            return
        row.status = status.value
        row.error_type = error_type
        row.error_message = error_message

    def mark_retrying(
        self,
        document_id: UUID,
        name: ProcessingStepName,
        error_type: str,
        error_message: str,
    ) -> None:
        row = self.session.scalar(
            select(ProcessingStepORM).where(
                ProcessingStepORM.document_id == document_id,
                ProcessingStepORM.name == name.value,
            )
        )
        if row is None:
            return
        row.status = ProcessingStepStatus.RETRYING.value
        row.attempt_count += 1
        row.error_type = error_type
        row.error_message = error_message
