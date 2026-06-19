from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models import ExtractedDataORM
from app.domain.models import ExtractedDataState
from app.db.mappers import extracted_data_to_state


class ExtractedDataRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, document_id: UUID) -> ExtractedDataState | None:
        row = self.session.get(ExtractedDataORM, document_id)
        return extracted_data_to_state(row) if row is not None else None

    def create_empty(self, document_id: UUID) -> None:
        self._get_or_create(document_id)

    def set_ocr_text(self, document_id: UUID, text: str) -> None:
        row = self._get_or_create(document_id)
        row.ocr_text = text

    def set_metadata(self, document_id: UUID, metadata: dict) -> None:
        row = self._get_or_create(document_id)
        row.metadata_json = metadata

    def set_chunks(self, document_id: UUID, chunks: list[str]) -> None:
        row = self._get_or_create(document_id)
        row.chunks_json = chunks

    def set_partner_result(self, document_id: UUID, result: dict) -> None:
        row = self._get_or_create(document_id)
        row.partner_result_json = result

    def clear_outputs(
        self,
        document_id: UUID,
        *,
        ocr: bool = False,
        metadata: bool = False,
        chunks: bool = False,
        partner: bool = False,
    ) -> None:
        row = self.session.get(ExtractedDataORM, document_id)
        if row is None:
            return
        if ocr:
            row.ocr_text = None
        if metadata:
            row.metadata_json = None
        if chunks:
            row.chunks_json = None
        if partner:
            row.partner_result_json = None

    def _get_or_create(self, document_id: UUID) -> ExtractedDataORM:
        # The app disables autoflush; pending rows are not visible through session.get().
        for row in self.session.new:
            if isinstance(row, ExtractedDataORM) and row.document_id == document_id:
                return row
        row = self.session.get(ExtractedDataORM, document_id)
        if row is None:
            row = ExtractedDataORM(document_id=document_id)
            self.session.add(row)
        return row
