from unittest.mock import Mock, call
from uuid import UUID

from app.domain.enums import DocumentStatus, ProcessingStepName, ProcessingStepStatus
from app.modules.processing.service import ProcessingService


def test_processing_service_initializes_all_pipeline_steps(
    document_id: UUID,
    document_repository: Mock,
    step_repository: Mock,
    extracted_data_repository: Mock,
) -> None:
    service = ProcessingService(
        documents=document_repository,
        steps=step_repository,
        extracted_data=extracted_data_repository,
    )

    service.initialize_pipeline(document_id, updated_by="unit-test")

    assert step_repository.upsert.call_args_list == [
        call(
            document_id=document_id,
            name=name,
            status=ProcessingStepStatus.PENDING,
            updated_by="unit-test",
        )
        for name in ProcessingStepName
    ]
    extracted_data_repository.create_empty.assert_called_once_with(document_id)
    document_repository.update_status.assert_called_once_with(document_id, DocumentStatus.PROCESSING)


def test_processing_service_marks_step_failure_and_document_failed(
    document_id: UUID,
    document_repository: Mock,
    step_repository: Mock,
    extracted_data_repository: Mock,
) -> None:
    service = ProcessingService(
        documents=document_repository,
        steps=step_repository,
        extracted_data=extracted_data_repository,
    )

    service.mark_step_failed(
        document_id=document_id,
        name=ProcessingStepName.OCR,
        error=TimeoutError("OCR provider timeout"),
    )

    step_repository.update_status.assert_called_once_with(
        document_id,
        ProcessingStepName.OCR,
        ProcessingStepStatus.FAILED,
        "TimeoutError",
        "OCR provider timeout",
    )
    document_repository.mark_failed.assert_called_once_with(
        document_id,
        "TimeoutError",
        "OCR provider timeout",
    )


def test_processing_service_stores_ocr_result_and_current_step_debug_payload(
    document_id: UUID,
    document_repository: Mock,
    step_repository: Mock,
    extracted_data_repository: Mock,
) -> None:
    service = ProcessingService(
        documents=document_repository,
        steps=step_repository,
        extracted_data=extracted_data_repository,
    )

    service.store_ocr_result(document_id, "lease raw text")

    extracted_data_repository.set_ocr_text.assert_called_once_with(document_id, "lease raw text")
    step_repository.set_result.assert_called_once_with(
        document_id,
        ProcessingStepName.OCR,
        {"ocr_text": "lease raw text"},
    )


def test_processing_service_completes_partner_webhook(
    document_id: UUID,
    document_repository: Mock,
    step_repository: Mock,
    extracted_data_repository: Mock,
) -> None:
    service = ProcessingService(
        documents=document_repository,
        steps=step_repository,
        extracted_data=extracted_data_repository,
    )

    service.mark_partner_completed(
        document_id,
        {"indexed_at": "2026-05-21T14:23:11Z"},
    )

    extracted_data_repository.set_partner_result.assert_called_once_with(
        document_id,
        {"indexed_at": "2026-05-21T14:23:11Z"},
    )
    step_repository.update_status.assert_called_once_with(
        document_id,
        ProcessingStepName.PARTNER_WEBHOOK,
        ProcessingStepStatus.SUCCESS,
    )
    step_repository.set_result.assert_called_once_with(
        document_id,
        ProcessingStepName.PARTNER_WEBHOOK,
        {"indexed_at": "2026-05-21T14:23:11Z"},
    )
    document_repository.update_status.assert_called_once_with(document_id, DocumentStatus.READY)


def test_processing_service_fails_partner_webhook(
    document_id: UUID,
    document_repository: Mock,
    step_repository: Mock,
    extracted_data_repository: Mock,
) -> None:
    service = ProcessingService(
        documents=document_repository,
        steps=step_repository,
        extracted_data=extracted_data_repository,
    )

    service.mark_partner_failed(document_id, "rejected")

    step_repository.update_status.assert_called_once_with(
        document_id,
        ProcessingStepName.PARTNER_WEBHOOK,
        ProcessingStepStatus.FAILED,
        "PartnerWebhookFailed",
        "partner returned status rejected",
    )
    document_repository.mark_failed.assert_called_once_with(
        document_id,
        "PartnerWebhookFailed",
        "partner returned status rejected",
    )
