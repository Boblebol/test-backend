from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


METABASE_URL = os.getenv("METABASE_URL", "http://127.0.0.1:3000").rstrip("/")
METABASE_EMAIL = os.getenv("METABASE_EMAIL", "admin@primmo.local")
METABASE_PASSWORD = os.getenv("METABASE_PASSWORD", "PrimmoAdmin2026!")
METABASE_FIRST_NAME = os.getenv("METABASE_FIRST_NAME", "Primmo")
METABASE_LAST_NAME = os.getenv("METABASE_LAST_NAME", "Admin")
PRIMMO_DB_HOST = os.getenv("METABASE_PRIMMO_DB_HOST", "postgres")
PRIMMO_DB_PORT = int(os.getenv("METABASE_PRIMMO_DB_PORT", "5432"))
PRIMMO_DB_NAME = os.getenv("METABASE_PRIMMO_DB_NAME", "primmo")
PRIMMO_DB_USER = os.getenv("METABASE_PRIMMO_DB_USER", "primmo")
PRIMMO_DB_PASSWORD = os.getenv("METABASE_PRIMMO_DB_PASSWORD", "primmo")
TRANSIENT_STARTUP_ERRORS = (HTTPError, URLError, TimeoutError, OSError)


@dataclass(frozen=True)
class MetabaseQuestion:
    name: str
    query: str
    display: str = "table"

    @property
    def description(self) -> str:
        return QUESTION_DESCRIPTIONS[self.name]

    @property
    def template_tags(self) -> tuple[str, ...]:
        return QUESTION_TEMPLATE_TAGS.get(self.name, ())


@dataclass(frozen=True)
class MetabaseDashboard:
    name: str
    description: str
    question_names: tuple[str, ...]
    parameter_ids: tuple[str, ...]
    collection_position: int


PARAMETER_DEFINITIONS = {
    "organization": {
        "id": "organization",
        "name": "Organization",
        "slug": "organization",
        "type": "category",
        "sectionId": "string",
    },
    "owner": {
        "id": "owner",
        "name": "Owner",
        "slug": "owner",
        "type": "category",
        "sectionId": "string",
    },
    "status": {
        "id": "status",
        "name": "Document status",
        "slug": "status",
        "type": "category",
        "sectionId": "string",
    },
}

TEMPLATE_TAG_DEFINITIONS = {
    "organization": {
        "id": "organization",
        "name": "organization",
        "display-name": "Organization",
        "type": "text",
        "required": False,
    },
    "owner": {
        "id": "owner",
        "name": "owner",
        "display-name": "Owner",
        "type": "text",
        "required": False,
    },
    "status": {
        "id": "status",
        "name": "status",
        "display-name": "Document status",
        "type": "text",
        "required": False,
    },
}


QUESTIONS = [
    MetabaseQuestion(
        name="Documents by status",
        display="bar",
        query="""
            select d.status, count(*) as documents
            from documents d
            join organizations o on o.id = d.org_id
            join users u on u.id = d.owner_user_id
            where true
              [[and o.name = {{organization}}]]
              [[and u.email = {{owner}}]]
              [[and d.status = {{status}}]]
            group by d.status
            order by documents desc;
        """,
    ),
    MetabaseQuestion(
        name="Active documents by current step",
        display="bar",
        query="""
            with active_steps as (
              select
                d.id,
                d.status as document_status,
                s.name as step,
                s.status as step_status,
                coalesce(s.attempt_count, 0) as attempt_count,
                row_number() over (
                  partition by d.id
                  order by
                    case
                      when s.status in ('running', 'retrying') then 1
                      when d.status = 'waiting_partner' and s.name = 'partner_webhook' then 2
                      when s.status = 'waiting_webhook' then 3
                      when s.status = 'failed' then 4
                      when s.status = 'pending' then 5
                      when s.status = 'success' then 6
                      else 7
                    end,
                    case s.name
                      when 'ocr' then 1
                      when 'metadata' then 2
                      when 'chunking' then 3
                      when 'external_call' then 4
                      when 'partner_webhook' then 5
                      else 99
                    end
                ) as step_rank
              from documents d
              join organizations o on o.id = d.org_id
              join users u on u.id = d.owner_user_id
              left join document_processing_steps s on s.document_id = d.id
              where d.status in ('uploaded', 'processing', 'waiting_partner')
                [[and o.name = {{organization}}]]
                [[and u.email = {{owner}}]]
                [[and d.status = {{status}}]]
            )
            select
              coalesce(step, 'no_step') as current_step,
              coalesce(step_status, document_status) as current_step_status,
              document_status,
              count(*) as documents,
              sum(attempt_count) as retry_attempts
            from active_steps
            where step_rank = 1
            group by current_step, current_step_status, document_status
            order by documents desc, current_step;
        """,
    ),
    MetabaseQuestion(
        name="Active documents detail",
        query="""
            with active_steps as (
              select
                d.id,
                d.original_filename,
                o.name as organization,
                u.email as owner,
                d.status as document_status,
                d.external_job_id,
                d.current_error_message,
                d.updated_at as document_updated_at,
                s.name as step,
                s.status as step_status,
                coalesce(s.attempt_count, 0) as attempt_count,
                s.updated_at as step_updated_at,
                row_number() over (
                  partition by d.id
                  order by
                    case
                      when s.status in ('running', 'retrying') then 1
                      when d.status = 'waiting_partner' and s.name = 'partner_webhook' then 2
                      when s.status = 'waiting_webhook' then 3
                      when s.status = 'failed' then 4
                      when s.status = 'pending' then 5
                      when s.status = 'success' then 6
                      else 7
                    end,
                    case s.name
                      when 'ocr' then 1
                      when 'metadata' then 2
                      when 'chunking' then 3
                      when 'external_call' then 4
                      when 'partner_webhook' then 5
                      else 99
                    end
                ) as step_rank
              from documents d
              join organizations o on o.id = d.org_id
              join users u on u.id = d.owner_user_id
              left join document_processing_steps s on s.document_id = d.id
              where d.status in ('uploaded', 'processing', 'waiting_partner')
                [[and o.name = {{organization}}]]
                [[and u.email = {{owner}}]]
            )
            select
              id as document_id,
              original_filename,
              organization,
              owner,
              document_status,
              coalesce(step, 'no_step') as current_step,
              coalesce(step_status, document_status) as current_step_status,
              attempt_count,
              round(extract(epoch from (now() - coalesce(step_updated_at, document_updated_at))) / 60, 1)
                as minutes_since_update,
              external_job_id,
              current_error_message
            from active_steps
            where step_rank = 1
            order by minutes_since_update desc, document_updated_at asc;
        """,
    ),
    MetabaseQuestion(
        name="Step status matrix",
        display="bar",
        query="""
            select
              s.name as step,
              s.status as step_status,
              count(*) as documents,
              sum(s.attempt_count) as retry_attempts,
              max(s.updated_at) as last_update_at
            from document_processing_steps s
            join documents d on d.id = s.document_id
            join organizations o on o.id = d.org_id
            join users u on u.id = d.owner_user_id
            where true
              [[and o.name = {{organization}}]]
              [[and u.email = {{owner}}]]
              [[and d.status = {{status}}]]
            group by s.name, s.status
            order by s.name, s.status;
        """,
    ),
    MetabaseQuestion(
        name="Retry attempts by step",
        display="bar",
        query="""
            select
              s.name as step,
              sum(s.attempt_count) as attempts,
              count(*) filter (where s.attempt_count > 0) as retried_documents
            from document_processing_steps s
            join documents d on d.id = s.document_id
            join organizations o on o.id = d.org_id
            join users u on u.id = d.owner_user_id
            where true
              [[and o.name = {{organization}}]]
              [[and u.email = {{owner}}]]
              [[and d.status = {{status}}]]
            group by s.name
            order by attempts desc, retried_documents desc;
        """,
    ),
    MetabaseQuestion(
        name="Failed documents by failed step",
        display="bar",
        query="""
            select
              coalesce(failed_step.name, 'document') as failed_step,
              coalesce(failed_step.error_type, d.current_error_type, 'unknown') as error_type,
              count(*) as documents
            from documents d
            join organizations o on o.id = d.org_id
            join users u on u.id = d.owner_user_id
            left join lateral (
              select name, error_type
              from document_processing_steps s
              where s.document_id = d.id and s.status = 'failed'
              order by s.updated_at desc
              limit 1
            ) failed_step on true
            where d.status = 'failed'
              [[and o.name = {{organization}}]]
              [[and u.email = {{owner}}]]
            group by
              coalesce(failed_step.name, 'document'),
              coalesce(failed_step.error_type, d.current_error_type, 'unknown')
            order by documents desc;
        """,
    ),
    MetabaseQuestion(
        name="Waiting partner documents by age",
        query="""
            select
              d.id as document_id,
              d.original_filename,
              o.name as organization,
              u.email as owner,
              d.external_job_id,
              round(extract(epoch from (now() - coalesce(s.updated_at, d.updated_at))) / 60, 1)
                as waiting_minutes,
              d.updated_at
            from documents d
            join organizations o on o.id = d.org_id
            join users u on u.id = d.owner_user_id
            left join document_processing_steps s
              on s.document_id = d.id and s.name = 'partner_webhook'
            where d.status = 'waiting_partner'
              [[and o.name = {{organization}}]]
              [[and u.email = {{owner}}]]
            order by waiting_minutes desc;
        """,
    ),
    MetabaseQuestion(
        name="Documents by organization",
        display="bar",
        query="""
            select o.name as organization, count(*) as documents
            from documents d
            join organizations o on o.id = d.org_id
            join users u on u.id = d.owner_user_id
            where true
              [[and o.name = {{organization}}]]
              [[and u.email = {{owner}}]]
              [[and d.status = {{status}}]]
            group by o.name
            order by documents desc;
        """,
    ),
    MetabaseQuestion(
        name="Documents by organization and status",
        display="bar",
        query="""
            select
              o.name as organization,
              d.status,
              count(*) as documents
            from documents d
            join organizations o on o.id = d.org_id
            join users u on u.id = d.owner_user_id
            where true
              [[and o.name = {{organization}}]]
              [[and u.email = {{owner}}]]
              [[and d.status = {{status}}]]
            group by o.name, d.status
            order by o.name, documents desc;
        """,
    ),
    MetabaseQuestion(
        name="Documents by user",
        display="bar",
        query="""
            select
              o.name as organization,
              u.email as owner,
              count(*) as documents,
              count(*) filter (where d.status = 'failed') as failed_documents,
              count(*) filter (where d.status = 'waiting_partner') as waiting_partner_documents
            from documents d
            join organizations o on o.id = d.org_id
            join users u on u.id = d.owner_user_id
            where true
              [[and o.name = {{organization}}]]
              [[and u.email = {{owner}}]]
              [[and d.status = {{status}}]]
            group by o.name, u.email
            order by documents desc, failed_documents desc;
        """,
    ),
    MetabaseQuestion(
        name="Failed documents by organization",
        display="bar",
        query="""
            select
              o.name as organization,
              count(*) as failed_documents
            from documents d
            join organizations o on o.id = d.org_id
            join users u on u.id = d.owner_user_id
            where d.status = 'failed'
              [[and o.name = {{organization}}]]
              [[and u.email = {{owner}}]]
            group by o.name
            order by failed_documents desc, organization;
        """,
    ),
    MetabaseQuestion(
        name="Waiting partner by organization",
        display="bar",
        query="""
            select
              o.name as organization,
              count(*) as waiting_partner_documents
            from documents d
            join organizations o on o.id = d.org_id
            join users u on u.id = d.owner_user_id
            where d.status = 'waiting_partner'
              [[and o.name = {{organization}}]]
              [[and u.email = {{owner}}]]
            group by o.name
            order by waiting_partner_documents desc, organization;
        """,
    ),
    MetabaseQuestion(
        name="Failed documents",
        query="""
            select
              d.id,
              d.original_filename,
              o.name as organization,
              u.email as owner,
              failed_step.name as failed_step,
              d.current_error_type,
              d.current_error_message,
              d.updated_at
            from documents d
            join organizations o on o.id = d.org_id
            join users u on u.id = d.owner_user_id
            left join lateral (
              select name
              from document_processing_steps s
              where s.document_id = d.id and s.status = 'failed'
              order by s.updated_at desc
              limit 1
            ) failed_step on true
            where d.status = 'failed'
              [[and o.name = {{organization}}]]
              [[and u.email = {{owner}}]]
            order by d.updated_at desc;
        """,
    ),
    MetabaseQuestion(
        name="Ready documents without OCR text",
        query="""
            select
              d.id as document_id,
              d.original_filename,
              o.name as organization,
              u.email as owner,
              d.updated_at
            from documents d
            join organizations o on o.id = d.org_id
            join users u on u.id = d.owner_user_id
            left join document_extracted_data e on e.document_id = d.id
            where d.status = 'ready'
              and nullif(trim(coalesce(e.ocr_text, '')), '') is null
              [[and o.name = {{organization}}]]
              [[and u.email = {{owner}}]]
            order by d.updated_at desc;
        """,
    ),
    MetabaseQuestion(
        name="Ready documents without metadata",
        query="""
            select
              d.id as document_id,
              d.original_filename,
              o.name as organization,
              u.email as owner,
              d.updated_at
            from documents d
            join organizations o on o.id = d.org_id
            join users u on u.id = d.owner_user_id
            left join document_extracted_data e on e.document_id = d.id
            where d.status = 'ready'
              and (e.metadata_json is null or e.metadata_json = '{}'::jsonb)
              [[and o.name = {{organization}}]]
              [[and u.email = {{owner}}]]
            order by d.updated_at desc;
        """,
    ),
    MetabaseQuestion(
        name="Ready documents without chunks",
        query="""
            select
              d.id as document_id,
              d.original_filename,
              o.name as organization,
              u.email as owner,
              d.updated_at
            from documents d
            join organizations o on o.id = d.org_id
            join users u on u.id = d.owner_user_id
            left join document_extracted_data e on e.document_id = d.id
            where d.status = 'ready'
              and (
                e.chunks_json is null
                or case
                  when jsonb_typeof(e.chunks_json) = 'array'
                    then jsonb_array_length(e.chunks_json) = 0
                  else true
                end
              )
              [[and o.name = {{organization}}]]
              [[and u.email = {{owner}}]]
            order by d.updated_at desc;
        """,
    ),
    MetabaseQuestion(
        name="Metadata doc types",
        display="bar",
        query="""
            select
              coalesce(e.metadata_json ->> 'doc_type', 'missing') as doc_type,
              count(*) as documents
            from documents d
            join organizations o on o.id = d.org_id
            join users u on u.id = d.owner_user_id
            left join document_extracted_data e on e.document_id = d.id
            where d.status = 'ready'
              [[and o.name = {{organization}}]]
              [[and u.email = {{owner}}]]
            group by coalesce(e.metadata_json ->> 'doc_type', 'missing')
            order by documents desc, doc_type;
        """,
    ),
    MetabaseQuestion(
        name="Partner result coverage",
        display="bar",
        query="""
            select
              case
                when e.partner_result_json is null or e.partner_result_json = '{}'::jsonb
                  then 'missing'
                else 'present'
              end as partner_result,
              count(*) as documents
            from documents d
            join organizations o on o.id = d.org_id
            join users u on u.id = d.owner_user_id
            left join document_extracted_data e on e.document_id = d.id
            where d.status = 'ready'
              [[and o.name = {{organization}}]]
              [[and u.email = {{owner}}]]
            group by partner_result
            order by partner_result;
        """,
    ),
    MetabaseQuestion(
        name="Snapshot data inconsistencies",
        query="""
            select
              'waiting_partner_without_external_job' as issue_type,
              d.id as document_id,
              d.original_filename,
              o.name as organization,
              u.email as owner,
              'missing external_job_id' as detail,
              d.updated_at
            from documents d
            join organizations o on o.id = d.org_id
            join users u on u.id = d.owner_user_id
            where d.status = 'waiting_partner'
              and d.external_job_id is null
              [[and o.name = {{organization}}]]
              [[and u.email = {{owner}}]]
            union all
            select
              'ready_without_partner_result' as issue_type,
              d.id as document_id,
              d.original_filename,
              o.name as organization,
              u.email as owner,
              'missing partner_result_json' as detail,
              d.updated_at
            from documents d
            join organizations o on o.id = d.org_id
            join users u on u.id = d.owner_user_id
            left join document_extracted_data e on e.document_id = d.id
            where d.status = 'ready'
              and (e.partner_result_json is null or e.partner_result_json = '{}'::jsonb)
              [[and o.name = {{organization}}]]
              [[and u.email = {{owner}}]]
            union all
            select
              'successful_ocr_without_result_json' as issue_type,
              d.id as document_id,
              d.original_filename,
              o.name as organization,
              u.email as owner,
              'ocr step is success but result_json is empty' as detail,
              s.updated_at
            from documents d
            join organizations o on o.id = d.org_id
            join users u on u.id = d.owner_user_id
            join document_processing_steps s on s.document_id = d.id
            where s.name = 'ocr'
              and s.status = 'success'
              and (s.result_json is null or s.result_json = '{}'::jsonb)
              [[and o.name = {{organization}}]]
              [[and u.email = {{owner}}]]
            order by updated_at desc;
        """,
    ),
]


QUESTION_DESCRIPTIONS = {
    "Documents by status": "Current document distribution by lifecycle status. This is a snapshot, not a trend.",
    "Active documents by current step": (
        "Estimated current bottleneck for uploaded, processing, and waiting-partner documents."
    ),
    "Active documents detail": "Triage list for active documents, sorted by time since the last snapshot update.",
    "Step status matrix": "Current status matrix for the latest persisted row of each processing step.",
    "Retry attempts by step": "Visible retry attempts stored on the current step row, grouped by step.",
    "Failed documents by failed step": "Current failed documents grouped by the latest failed step and error type.",
    "Waiting partner documents by age": (
        "Documents waiting for the asynchronous partner webhook, sorted by current waiting age."
    ),
    "Documents by organization": "Current document volume by organization.",
    "Documents by organization and status": "Current document volume by organization and lifecycle status.",
    "Documents by user": "Current document volume by uploading user, including failed and partner-waiting counts.",
    "Failed documents by organization": "Current failed-document count by organization for support prioritization.",
    "Waiting partner by organization": "Current partner-waiting document count by organization.",
    "Failed documents": (
        "Detailed list of documents currently in failed state with owner, organization, and last error."
    ),
    "Ready documents without OCR text": "Ready documents whose extracted OCR text is empty or missing.",
    "Ready documents without metadata": "Ready documents whose metadata payload is empty or missing.",
    "Ready documents without chunks": "Ready documents whose chunk list is empty, missing, or malformed.",
    "Metadata doc types": "Current distribution of metadata doc_type values for ready documents.",
    "Partner result coverage": "Ready documents grouped by whether partner_result_json is present.",
    "Snapshot data inconsistencies": "Current-state consistency checks that should normally return no rows.",
}

ORG_OWNER_STATUS_FILTERS = ("organization", "owner", "status")
ORG_OWNER_FILTERS = ("organization", "owner")

QUESTION_TEMPLATE_TAGS = {
    "Documents by status": ORG_OWNER_STATUS_FILTERS,
    "Active documents by current step": ORG_OWNER_STATUS_FILTERS,
    "Step status matrix": ORG_OWNER_STATUS_FILTERS,
    "Retry attempts by step": ORG_OWNER_STATUS_FILTERS,
    "Active documents detail": ORG_OWNER_FILTERS,
    "Failed documents": ORG_OWNER_FILTERS,
    "Failed documents by failed step": ORG_OWNER_FILTERS,
    "Waiting partner documents by age": ORG_OWNER_FILTERS,
    "Snapshot data inconsistencies": ORG_OWNER_FILTERS,
    "Documents by organization": ORG_OWNER_STATUS_FILTERS,
    "Documents by organization and status": ORG_OWNER_STATUS_FILTERS,
    "Documents by user": ORG_OWNER_STATUS_FILTERS,
    "Failed documents by organization": ORG_OWNER_FILTERS,
    "Waiting partner by organization": ORG_OWNER_FILTERS,
    "Ready documents without OCR text": ORG_OWNER_FILTERS,
    "Ready documents without metadata": ORG_OWNER_FILTERS,
    "Ready documents without chunks": ORG_OWNER_FILTERS,
    "Metadata doc types": ORG_OWNER_FILTERS,
    "Partner result coverage": ORG_OWNER_FILTERS,
}


DASHBOARDS = [
    MetabaseDashboard(
        name="Primmo operations snapshot",
        description="Current operational snapshot for active documents and processing steps.",
        question_names=(
            "Documents by status",
            "Active documents by current step",
            "Step status matrix",
            "Retry attempts by step",
        ),
        parameter_ids=ORG_OWNER_STATUS_FILTERS,
        collection_position=1,
    ),
    MetabaseDashboard(
        name="Primmo problem documents",
        description="Triage dashboard for failed, stale, inconsistent, and partner-waiting documents.",
        question_names=(
            "Active documents detail",
            "Failed documents",
            "Failed documents by failed step",
            "Waiting partner documents by age",
            "Snapshot data inconsistencies",
        ),
        parameter_ids=ORG_OWNER_FILTERS,
        collection_position=2,
    ),
    MetabaseDashboard(
        name="Primmo usage",
        description="Current usage breakdown by organization and user.",
        question_names=(
            "Documents by organization",
            "Documents by organization and status",
            "Documents by user",
            "Failed documents by organization",
            "Waiting partner by organization",
        ),
        parameter_ids=ORG_OWNER_STATUS_FILTERS,
        collection_position=3,
    ),
    MetabaseDashboard(
        name="Primmo data quality",
        description="Current extracted-data completeness and quality checks.",
        question_names=(
            "Ready documents without OCR text",
            "Ready documents without metadata",
            "Ready documents without chunks",
            "Metadata doc types",
            "Partner result coverage",
        ),
        parameter_ids=ORG_OWNER_FILTERS,
        collection_position=4,
    ),
]

DASHBOARD_CARD_LAYOUTS = {
    "Primmo operations snapshot": {
        "Documents by status": (0, 0, 6, 5),
        "Active documents by current step": (0, 6, 6, 5),
        "Step status matrix": (5, 0, 6, 6),
        "Retry attempts by step": (5, 6, 6, 6),
    },
    "Primmo problem documents": {
        "Active documents detail": (0, 0, 12, 7),
        "Failed documents": (7, 0, 12, 7),
        "Failed documents by failed step": (14, 0, 6, 5),
        "Waiting partner documents by age": (14, 6, 6, 5),
        "Snapshot data inconsistencies": (19, 0, 12, 7),
    },
    "Primmo usage": {
        "Documents by organization": (0, 0, 6, 5),
        "Documents by organization and status": (0, 6, 6, 5),
        "Documents by user": (5, 0, 12, 7),
        "Failed documents by organization": (12, 0, 6, 5),
        "Waiting partner by organization": (12, 6, 6, 5),
    },
    "Primmo data quality": {
        "Metadata doc types": (0, 0, 6, 5),
        "Partner result coverage": (0, 6, 6, 5),
        "Ready documents without OCR text": (5, 0, 4, 7),
        "Ready documents without metadata": (5, 4, 4, 7),
        "Ready documents without chunks": (5, 8, 4, 7),
    },
}


class MetabaseClient:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.session_token: str | None = None

    def get(self, path: str) -> Any:
        return self._request("GET", path)

    def post(self, path: str, payload: dict[str, Any]) -> Any:
        return self._request("POST", path, payload)

    def put(self, path: str, payload: dict[str, Any]) -> Any:
        return self._request("PUT", path, payload)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        data = None
        headers = {"Content-Type": "application/json"}
        if self.session_token:
            headers["X-Metabase-Session"] = self.session_token
        if payload is not None:
            data = json.dumps(payload).encode()
        request = Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        with urlopen(request, timeout=20) as response:
            body = response.read()
        if not body:
            return None
        return json.loads(body.decode())


def main() -> int:
    client = MetabaseClient(METABASE_URL)
    if not wait_for_metabase(client):
        print(f"Metabase did not become ready at {METABASE_URL}", file=sys.stderr)
        return 1

    setup_or_login(client)
    database_id = ensure_database(client)
    dashboard_ids_by_name = ensure_dashboards(client)
    card_ids_by_name = ensure_questions(client, database_id)
    attach_cards_to_dashboards(client, dashboard_ids_by_name, card_ids_by_name)

    print(f"Metabase ready: {METABASE_URL}")
    print(f"Login: {METABASE_EMAIL} / {METABASE_PASSWORD}")
    print("Dashboards:")
    for dashboard in DASHBOARDS:
        print(f"- {dashboard.name}")
    return 0


def wait_for_metabase(client: MetabaseClient) -> bool:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            client.get("/api/session/properties")
            return True
        except TRANSIENT_STARTUP_ERRORS:
            time.sleep(2)
    return False


def setup_or_login(client: MetabaseClient) -> None:
    properties = client.get("/api/session/properties")
    setup_token = properties.get("setup-token")
    if setup_token and not properties.get("has-user-setup"):
        payload = {
            "token": setup_token,
            "user": {
                "first_name": METABASE_FIRST_NAME,
                "last_name": METABASE_LAST_NAME,
                "email": METABASE_EMAIL,
                "password": METABASE_PASSWORD,
            },
            "prefs": {
                "site_name": "Primmo Local",
                "site_locale": "en",
                "allow_tracking": False,
            },
            "database": primmo_database_payload(),
        }
        response = client.post("/api/setup", payload)
        client.session_token = response["id"]
        return

    response = client.post(
        "/api/session",
        {
            "username": METABASE_EMAIL,
            "password": METABASE_PASSWORD,
        },
    )
    client.session_token = response["id"]


def ensure_database(client: MetabaseClient) -> int:
    databases = client.get("/api/database")
    for database in databases.get("data", []):
        if database.get("name") == "Primmo Postgres":
            return int(database["id"])
    response = client.post("/api/database", primmo_database_payload())
    return int(response["id"])


def primmo_database_payload() -> dict[str, Any]:
    return {
        "name": "Primmo Postgres",
        "engine": "postgres",
        "details": {
            "host": PRIMMO_DB_HOST,
            "port": PRIMMO_DB_PORT,
            "dbname": PRIMMO_DB_NAME,
            "user": PRIMMO_DB_USER,
            "password": PRIMMO_DB_PASSWORD,
            "ssl": False,
        },
    }


def ensure_dashboards(client: MetabaseClient) -> dict[str, int]:
    dashboards = client.get("/api/dashboard")
    dashboard_list = dashboards if isinstance(dashboards, list) else dashboards.get("data", [])
    existing_by_name = {
        dashboard["name"]: int(dashboard["id"])
        for dashboard in dashboard_list
        if dashboard.get("name")
    }
    dashboard_ids_by_name: dict[str, int] = {}
    for dashboard in DASHBOARDS:
        payload = dashboard_payload(dashboard)
        if dashboard.name in existing_by_name:
            dashboard_id = existing_by_name[dashboard.name]
            client.put(f"/api/dashboard/{dashboard_id}", payload)
            dashboard_ids_by_name[dashboard.name] = dashboard_id
            continue
        response = client.post("/api/dashboard", payload)
        dashboard_ids_by_name[dashboard.name] = int(response["id"])
    return dashboard_ids_by_name


def ensure_dashboard(client: MetabaseClient) -> int:
    dashboard_ids_by_name = ensure_dashboards(client)
    return dashboard_ids_by_name["Primmo operations snapshot"]


def ensure_questions(client: MetabaseClient, database_id: int) -> dict[str, int]:
    existing_cards = client.get("/api/card")
    card_list = existing_cards if isinstance(existing_cards, list) else existing_cards.get("data", [])
    existing_by_name = {
        card["name"]: int(card["id"])
        for card in card_list
        if card.get("name")
    }
    card_ids_by_name: dict[str, int] = {}
    for question in QUESTIONS:
        payload = question_payload(question, database_id)
        if question.name in existing_by_name:
            card_id = existing_by_name[question.name]
            client.put(f"/api/card/{card_id}", payload)
            card_ids_by_name[question.name] = card_id
            continue
        response = client.post("/api/card", payload)
        card_ids_by_name[question.name] = int(response["id"])
    return card_ids_by_name


def question_payload(question: MetabaseQuestion, database_id: int) -> dict[str, Any]:
    return {
        "name": question.name,
        "description": question.description,
        "display": question.display,
        "dataset_query": {
            "database": database_id,
            "type": "native",
            "native": {
                "query": normalize_sql(question.query),
                "template-tags": template_tags_payload(question),
            },
        },
        "visualization_settings": {},
    }


def attach_cards_to_dashboards(
    client: MetabaseClient,
    dashboard_ids_by_name: dict[str, int],
    card_ids_by_name: dict[str, int],
) -> None:
    for dashboard in DASHBOARDS:
        card_ids = [
            card_ids_by_name[question_name]
            for question_name in dashboard.question_names
        ]
        attach_cards_to_dashboard(
            client,
            dashboard_ids_by_name[dashboard.name],
            card_ids,
            dashboard,
        )


def attach_cards_to_dashboard(
    client: MetabaseClient,
    dashboard_id: int,
    card_ids: list[int],
    dashboard: MetabaseDashboard | None = None,
) -> None:
    dashboard = dashboard or DASHBOARDS[0]
    dashcards = []
    for index, (question_name, card_id) in enumerate(
        zip(dashboard.question_names, card_ids, strict=True)
    ):
        question = question_by_name(question_name)
        row, col, size_x, size_y = dashboard_card_layout(dashboard, question_name, index)
        dashcards.append(
            {
                "id": -(index + 1),
                "card_id": card_id,
                "row": row,
                "col": col,
                "size_x": size_x,
                "size_y": size_y,
                "parameter_mappings": parameter_mappings_for_question(dashboard, question, card_id),
                "series": [],
            }
        )
    payload = dashboard_payload(dashboard)
    payload.update(
        {
            "dashcards": dashcards,
            "parameters": dashboard_parameters(dashboard),
        }
    )
    client.put(f"/api/dashboard/{dashboard_id}", payload)


def dashboard_payload(dashboard: MetabaseDashboard) -> dict[str, Any]:
    return {
        "name": dashboard.name,
        "description": dashboard.description,
        "collection_id": None,
        "collection_position": dashboard.collection_position,
    }


def question_by_name(question_name: str) -> MetabaseQuestion:
    for question in QUESTIONS:
        if question.name == question_name:
            return question
    raise KeyError(question_name)


def template_tags_payload(question: MetabaseQuestion) -> dict[str, dict[str, Any]]:
    return {
        tag_name: TEMPLATE_TAG_DEFINITIONS[tag_name]
        for tag_name in question.template_tags
    }


def dashboard_parameters(dashboard: MetabaseDashboard) -> list[dict[str, Any]]:
    return [
        PARAMETER_DEFINITIONS[parameter_id]
        for parameter_id in dashboard.parameter_ids
    ]


def parameter_mappings_for_question(
    dashboard: MetabaseDashboard,
    question: MetabaseQuestion,
    card_id: int,
) -> list[dict[str, Any]]:
    return [
        {
            "parameter_id": parameter_id,
            "card_id": card_id,
            "target": ["dimension", ["template-tag", parameter_id]],
        }
        for parameter_id in dashboard.parameter_ids
        if parameter_id in question.template_tags
    ]


def dashboard_card_layout(
    dashboard: MetabaseDashboard,
    question_name: str,
    index: int,
) -> tuple[int, int, int, int]:
    layout = DASHBOARD_CARD_LAYOUTS.get(dashboard.name, {}).get(question_name)
    if layout is not None:
        return layout
    return index * 6, 0, 12, 6


def normalize_sql(query: str) -> str:
    return "\n".join(line.strip() for line in query.strip().splitlines())


if __name__ == "__main__":
    raise SystemExit(main())
