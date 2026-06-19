from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import ContextManager
from uuid import UUID

from flask import Flask, abort, redirect, render_template_string, request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.domain.enums import DocumentStatus
from app.modules.admin.document_uploads import (
    AdminDocumentUploadActions,
    AdminDocumentUploadResult,
)
from app.modules.admin.partner_webhook_actions import AdminPartnerWebhookActions
from app.modules.admin.pipeline_actions import AdminPipelineActionResult, AdminPipelineActions
from app.modules.admin.queries import (
    AdminDocumentFilters,
    AdminQueries,
    AdminUserFilters,
)
from app.modules.documents.storage import S3ObjectStorage
from app.modules.processing.pipeline import PipelineOrchestrator, PipelineStrategyName, UnknownPipelineStrategy


SessionScope = Callable[[], ContextManager[Session]]
StorageFactory = Callable[[], S3ObjectStorage]
PipelineFactory = Callable[[], PipelineOrchestrator]
PARTNER_WEBHOOK_COMPLETED_ACTION = "partner_webhook_completed"
PARTNER_WEBHOOK_REJECTED_ACTION = "partner_webhook_rejected"
PIPELINE_RELAUNCH_ACTION_PREFIX = "pipeline_relaunch:"
PIPELINE_RELAUNCH_ACTIONS = (
    (f"{PIPELINE_RELAUNCH_ACTION_PREFIX}{PipelineStrategyName.ALL.value}", "Rerun full pipeline"),
    (f"{PIPELINE_RELAUNCH_ACTION_PREFIX}{PipelineStrategyName.OCR.value}", "Rerun from OCR"),
    (f"{PIPELINE_RELAUNCH_ACTION_PREFIX}{PipelineStrategyName.POST_OCR.value}", "Rerun after OCR"),
    (f"{PIPELINE_RELAUNCH_ACTION_PREFIX}{PipelineStrategyName.METADATA.value}", "Rerun metadata"),
    (f"{PIPELINE_RELAUNCH_ACTION_PREFIX}{PipelineStrategyName.CHUNKING.value}", "Rerun chunking"),
    (f"{PIPELINE_RELAUNCH_ACTION_PREFIX}{PipelineStrategyName.EXTERNAL_CALL.value}", "Rerun external call"),
)


@contextmanager
def default_session_scope() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def default_storage_factory() -> S3ObjectStorage:
    settings = get_settings()
    return S3ObjectStorage(
        endpoint=settings.minio_endpoint,
        public_endpoint=settings.minio_public_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        region=settings.minio_region,
    )


def default_pipeline_factory() -> PipelineOrchestrator:
    return PipelineOrchestrator()


def create_admin_app(
    session_scope: SessionScope = default_session_scope,
    storage_factory: StorageFactory = default_storage_factory,
    pipeline_factory: PipelineFactory = default_pipeline_factory,
) -> Flask:
    app = Flask(__name__)

    @app.get("/health")
    def health():
        return {"service": "admin", "status": "ok"}

    @app.get("/test-cockpit")
    def test_cockpit():
        filters = _document_filters_from_request(
            default_status=DocumentStatus.WAITING_PARTNER.value,
            default_limit=50,
        )
        with session_scope() as session:
            queries = AdminQueries(session)
            rows = queries.list_documents(filters)
            organizations = queries.list_organizations()
            users = queries.list_users(AdminUserFilters(org_id=filters.org_id))
            all_users = queries.list_users()
        return _render_page(
            title="Test Cockpit",
            auto_refresh_seconds=10,
            body=_render_test_cockpit(
                filters=filters,
                organizations=organizations,
                rows=rows,
                users=users,
                all_users=all_users,
            ),
        )

    @app.post("/test-cockpit/documents")
    def create_test_cockpit_documents():
        owner_user_id = _parse_uuid(request.form.get("owner_user_id"))
        document_count = _parse_bounded_int(
            request.form.get("document_count"),
            min_value=1,
            max_value=200,
        )
        filename_prefix = (request.form.get("filename_prefix") or "cockpit-lease").strip()

        settings = get_settings()
        with session_scope() as session:
            upload_actions = AdminDocumentUploadActions(
                session,
                storage=storage_factory(),
                settings=settings,
            )
            results = upload_actions.generate_fake_documents_for_user(
                owner_user_id=owner_user_id,
                document_count=document_count,
                filename_prefix=filename_prefix,
            )
            session.commit()

        pipeline = pipeline_factory()
        results = _enqueue_uploaded_documents(results, pipeline)
        return _render_document_upload_results(results)

    @app.get("/")
    def home():
        return redirect("/test-cockpit")

    @app.get("/documents/new")
    def new_documents():
        with session_scope() as session:
            users = AdminQueries(session).list_users()
        return _render_new_documents_form(users=users)

    @app.post("/documents/new")
    def create_documents_from_admin():
        owner_user_id = _parse_uuid(request.form.get("owner_user_id"))
        files = [file for file in request.files.getlist("files") if file.filename]
        if not files:
            return _render_document_upload_results([])

        settings = get_settings()
        with session_scope() as session:
            upload_actions = AdminDocumentUploadActions(
                session,
                storage=storage_factory(),
                settings=settings,
            )
            results = upload_actions.create_uploaded_documents(
                owner_user_id=owner_user_id,
                files=files,
            )
            session.commit()

        pipeline = pipeline_factory()
        results = _enqueue_uploaded_documents(results, pipeline)
        return _render_document_upload_results(results)

    @app.post("/documents/generate-fake-batch")
    def generate_fake_documents_from_admin():
        organization_name = (request.form.get("organization_name") or "").strip()
        if not organization_name:
            abort(400)
        user_count = _parse_bounded_int(
            request.form.get("user_count"),
            min_value=1,
            max_value=50,
        )
        document_count = _parse_bounded_int(
            request.form.get("document_count"),
            min_value=1,
            max_value=1000,
        )
        filename_prefix = (request.form.get("filename_prefix") or "load-test-lease").strip()

        settings = get_settings()
        with session_scope() as session:
            upload_actions = AdminDocumentUploadActions(
                session,
                storage=storage_factory(),
                settings=settings,
            )
            results = upload_actions.generate_fake_batch(
                organization_name=organization_name,
                user_count=user_count,
                document_count=document_count,
                filename_prefix=filename_prefix,
            )
            session.commit()

        pipeline = pipeline_factory()
        results = _enqueue_uploaded_documents(results, pipeline)
        return _render_document_upload_results(results)

    @app.post("/documents/actions")
    def document_actions():
        action = request.form.get("action")
        raw_ids = request.form.getlist("rowid")
        if action == PARTNER_WEBHOOK_COMPLETED_ACTION:
            return _complete_partner_webhook_action(raw_ids)
        if action == PARTNER_WEBHOOK_REJECTED_ACTION:
            return _reject_partner_webhook_action(raw_ids)
        strategy = _pipeline_strategy_from_action(action)
        if strategy is not None:
            return _relaunch_pipeline_action(raw_ids, strategy)
        abort(400)

    @app.post("/documents/actions/partner-webhook-completed")
    def complete_partner_webhook():
        raw_ids = request.form.getlist("document_ids") or request.form.getlist("rowid")
        return _complete_partner_webhook_action(raw_ids)

    def _complete_partner_webhook_action(raw_document_ids: list[str]):
        document_ids = _parse_document_ids(raw_document_ids)
        if not document_ids:
            return _render_partner_webhook_results([])

        with session_scope() as session:
            results = AdminPartnerWebhookActions(
                session,
                hmac_secret=get_settings().partner_hmac_secret,
            ).complete_documents(document_ids)
            session.commit()
        return _render_partner_webhook_results(results)

    def _reject_partner_webhook_action(raw_document_ids: list[str]):
        document_ids = _parse_document_ids(raw_document_ids)
        if not document_ids:
            return _render_partner_webhook_results([])

        with session_scope() as session:
            results = AdminPartnerWebhookActions(
                session,
                hmac_secret=get_settings().partner_hmac_secret,
            ).reject_documents(document_ids)
            session.commit()
        return _render_partner_webhook_results(results)

    def _relaunch_pipeline_action(raw_document_ids: list[str], strategy: PipelineStrategyName):
        document_ids = _parse_document_ids(raw_document_ids)
        if not document_ids:
            return _render_pipeline_relaunch_results([])

        with session_scope() as session:
            try:
                results = AdminPipelineActions(session).prepare_documents(document_ids, strategy)
            except UnknownPipelineStrategy:
                abort(400)
            session.commit()

        pipeline = pipeline_factory()
        results = _enqueue_pipeline_relaunches(results, pipeline)
        return _render_pipeline_relaunch_results(results)

    @app.get("/documents/<uuid:document_id>/actions")
    def document_action_page(document_id: UUID):
        with session_scope() as session:
            queries = AdminQueries(session)
            detail = queries.get_document_detail(document_id)
            if detail is None:
                abort(404)
            previews = AdminPartnerWebhookActions(
                session,
                hmac_secret=get_settings().partner_hmac_secret,
            ).preview_document(document_id)
        return _render_page(
            title="Document action",
            body=render_template_string(
                """
                <p><a href="/documents/{{ detail.document.id }}">Back to document detail</a></p>
                <section class="details">
                  <dl>
                    <div><dt>Filename</dt><dd>{{ detail.document.original_filename }}</dd></div>
                    <div><dt>Status</dt><dd><code>{{ detail.document.status }}</code></dd></div>
                    <div><dt>Organization</dt><dd>{{ detail.document.organization_name }}</dd></div>
                    <div><dt>Owner</dt><dd>{{ detail.document.owner_email }}</dd></div>
                    <div><dt>External job</dt><dd>{{ detail.document.external_job_id or "-" }}</dd></div>
                    <div><dt>Error</dt><dd>{{ detail.document.current_error_type or "-" }}</dd></div>
                  </dl>
                </section>

                <section class="model-list action-panel">
                  <div class="model-list-toolbar">
                    <div>
                      <strong>Apply partner webhook result</strong>
                      <span class="selection-count">1 selected</span>
                    </div>
                    <a class="btn btn-secondary" href="/test-cockpit">← Test Cockpit</a>
                  </div>
                  <div class="action-buttons">
                    <form method="post" action="/documents/actions" data-confirm-message="Validate this document?">
                      <input type="hidden" name="rowid" value="{{ detail.document.id }}">
                      <input type="hidden" name="action" value="partner_webhook_completed">
                      <button class="btn btn-primary" type="submit">Validate document</button>
                    </form>
                    <form method="post" action="/documents/actions" data-confirm-message="Invalidate this document?">
                      <input type="hidden" name="rowid" value="{{ detail.document.id }}">
                      <input type="hidden" name="action" value="partner_webhook_rejected">
                      <button class="btn btn-danger" type="submit">Invalidate document</button>
                    </form>
                  </div>
                </section>

                <h2>Webhook payload preview</h2>
                <table>
                  <thead>
                    <tr>
                      <th>Status</th>
                      <th>Signature</th>
                      <th>Request body</th>
                    </tr>
                  </thead>
                  <tbody>
                    {% for preview in previews %}
                    <tr>
                      <td><code>{{ preview.status }}</code></td>
                      <td><code>{{ preview.signature or "-" }}</code></td>
                      <td>{% if preview.request_body %}<pre>{{ preview.request_body | safe }}</pre>{% else %}{{ preview.message }}{% endif %}</td>
                    </tr>
                    {% endfor %}
                  </tbody>
                </table>

                <section class="model-list action-panel">
                  <div class="model-list-toolbar">
                    <div>
                      <strong>Rerun pipeline</strong>
                      <span class="selection-count">1 selected</span>
                    </div>
                  </div>
                  <div class="action-buttons">
                    {% for value, label in pipeline_actions %}
                    <form method="post" action="/documents/actions" data-confirm-message="{{ label }} for this document?">
                      <input type="hidden" name="rowid" value="{{ detail.document.id }}">
                      <input type="hidden" name="action" value="{{ value }}">
                      <button class="btn btn-secondary" type="submit">{{ label }}</button>
                    </form>
                    {% endfor %}
                  </div>
                </section>
                """,
                detail=detail,
                pipeline_actions=PIPELINE_RELAUNCH_ACTIONS,
                previews=previews,
            ),
        )

    @app.get("/documents/<uuid:document_id>")
    def document_detail(document_id: UUID):
        with session_scope() as session:
            detail = AdminQueries(session).get_document_detail(document_id)
        if detail is None:
            abort(404)
        return _render_page(
            title=f"Document — {detail.document.original_filename}",
            auto_refresh_seconds=6,
            body=render_template_string(
                """
                <section class="details">
                  <dl>
                    <div><dt>Status</dt><dd><code>{{ detail.document.status }}</code></dd></div>
                    <div><dt>Organization</dt><dd>{{ detail.document.organization_name }}</dd></div>
                    <div><dt>Owner</dt><dd>{{ detail.document.owner_email }}</dd></div>
                    <div><dt>External job</dt><dd>{{ detail.document.external_job_id or "-" }}</dd></div>
                    <div><dt>Storage key</dt><dd><code>{{ detail.storage_key }}</code></dd></div>
                    <div><dt>Error</dt><dd>{{ detail.document.current_error_type or "-" }}</dd></div>
                    <div><dt>Created</dt><dd>{{ format_datetime(detail.document.created_at) }}</dd></div>
                    <div><dt>Updated</dt><dd>{{ format_datetime(detail.updated_at) }}</dd></div>
                  </dl>
                </section>
                <div class="page-actions">
                  <a class="btn btn-secondary" href="/test-cockpit">← Test Cockpit</a>
                  <a class="btn btn-primary" href="/documents/{{ detail.document.id }}/actions">Apply webhook / relaunch</a>
                </div>

                <h2>Pipeline</h2>
                {% if detail.steps %}
                <div class="pipeline-track">
                  {% for step in detail.steps %}
                  <div class="pipeline-step step-{{ step.status }}">
                    <div class="pipeline-step-name">{{ step.name }}</div>
                    <div class="pipeline-step-status">{{ step.status }}</div>
                    {% if step.attempt_count > 1 %}
                    <div style="font-size:10px;margin-top:2px;opacity:.7">{{ step.attempt_count }} attempts</div>
                    {% endif %}
                  </div>
                  {% endfor %}
                </div>
                {% endif %}
                <table id="steps-table">
                  <thead>
                    <tr>
                      <th>Step</th>
                      <th>Status</th>
                      <th>Attempts</th>
                      <th>Updated by</th>
                      <th>Result</th>
                      <th>Error</th>
                      <th>Updated</th>
                    </tr>
                  </thead>
                  <tbody>
                    {% for step in detail.steps %}
                    <tr>
                      <td><code>{{ step.name }}</code></td>
                      <td><code>{{ step.status }}</code></td>
                      <td>{{ step.attempt_count }}</td>
                      <td>{{ step.updated_by or "-" }}</td>
                      <td>{% if step.result_json %}<pre>{{ step.result_json | tojson(indent=2) }}</pre>{% else %}-{% endif %}</td>
                      <td>{{ step.error_type or step.error_message or "-" }}</td>
                      <td>{{ format_datetime(step.updated_at) }}</td>
                    </tr>
                    {% endfor %}
                    {% if not detail.steps %}
                    <tr>
                      <td colspan="7">No processing steps yet.</td>
                    </tr>
                    {% endif %}
                  </tbody>
                </table>
                """,
                detail=detail,
                format_datetime=_format_datetime,
            ),
        )

    return app


app = create_admin_app()


def _render_test_cockpit(
    *,
    filters: AdminDocumentFilters,
    organizations,
    rows,
    users,
    all_users,
) -> str:
    return render_template_string(
        """
        <p class="intro">
          One-page flow for the technical test review. Create documents, watch the pipeline run, then apply the partner webhook.
          Page auto-refreshes every 10 s — keep it open while the pipeline runs.
        </p>

        <div class="pipeline-track" style="margin-bottom:24px">
          <div class="pipeline-step step-pending">
            <div class="pipeline-step-name">① OCR</div>
            <div class="pipeline-step-status" style="color:inherit;opacity:.7">1–15 s</div>
          </div>
          <div class="pipeline-step step-pending">
            <div class="pipeline-step-name">② metadata</div>
            <div class="pipeline-step-status" style="color:inherit;opacity:.7">parallel</div>
          </div>
          <div class="pipeline-step step-pending">
            <div class="pipeline-step-name">② chunking</div>
            <div class="pipeline-step-status" style="color:inherit;opacity:.7">parallel</div>
          </div>
          <div class="pipeline-step step-pending">
            <div class="pipeline-step-name">③ external_call</div>
            <div class="pipeline-step-status" style="color:inherit;opacity:.7">→ job_id</div>
          </div>
          <div class="pipeline-step" style="background:rgba(210,153,34,.08);border-color:rgba(210,153,34,.3);color:var(--amber)">
            <div class="pipeline-step-name">④ webhook</div>
            <div class="pipeline-step-status">waiting_partner</div>
          </div>
          <div class="pipeline-step step-completed" style="border-radius:0 var(--radius) var(--radius) 0">
            <div class="pipeline-step-name">⑤ ready</div>
            <div class="pipeline-step-status">done</div>
          </div>
        </div>

        <section class="metric-grid">
          <a class="metric-card" href="/documents/new">
            <span>Upload</span>
            <strong>Add PDFs</strong>
          </a>
          <a class="metric-card accent" href="/test-cockpit?status=waiting_partner">
            <span>Waiting webhook</span>
            <strong>↓ Act here</strong>
          </a>
        </section>

        <section class="dashboard-grid">
          <div class="panel">
            <div class="section-head">
              <h2>Create documents for a user</h2>
              <a href="/documents/new">Open full upload form</a>
            </div>
            <form class="admin-form" method="post" action="/test-cockpit/documents">
              <div class="form-field">
                <label for="cockpit-owner-user-id">User</label>
                <select id="cockpit-owner-user-id" name="owner_user_id" required>
                  {% for user in all_users %}
                  <option value="{{ user.id }}">{{ user.email }} - {{ user.organization_name }}</option>
                  {% endfor %}
                </select>
              </div>
              <div class="form-field">
                <label for="cockpit-document-count">Documents to create</label>
                <input id="cockpit-document-count" type="number" name="document_count" min="1" max="200" value="5" required>
              </div>
              <div class="form-field">
                <label for="cockpit-filename-prefix">Filename prefix</label>
                <input id="cockpit-filename-prefix" type="text" name="filename_prefix" value="cockpit-lease" required>
              </div>
              <button class="btn btn-primary" type="submit">Create fake PDFs and launch pipelines</button>
            </form>
          </div>

          <div class="panel">
            <h2>Review checklist</h2>
            <ol class="workflow-list">
              <li>Create fake documents for a seeded user below.</li>
              <li>Click a document link → watch per-step pipeline track (auto-refresh).</li>
              <li>Wait for <code>waiting_partner</code> status after external_call completes.</li>
              <li>Select documents below → choose <em>Validate webhook</em> → Apply action.</li>
              <li>Document moves to <code>ready</code>. Check <code>result_json</code> in processing steps.</li>
            </ol>
            <div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:4px">
              <a class="btn btn-secondary" href="/documents/new">Upload real PDFs</a>
            </div>
          </div>
        </section>

        <section class="panel">
          <div class="section-head">
            <h2>Action queue</h2>
          </div>
          {{ render_document_filters(filters, organizations, users, "/test-cockpit", submit_label="Refresh queue") | safe }}
          <form
            id="cockpit-action-form"
            class="model-list"
            method="post"
            action="/documents/actions"
            data-confirm-message="Apply this action to the selected documents?"
          >
            <div class="model-list-toolbar">
              <div>
                <strong>Bulk actions</strong>
                <span class="selection-count" data-selected-count>0 selected</span>
              </div>
              <div class="action-controls">
                <label class="sr-only" for="cockpit-document-action">Document action</label>
                <select id="cockpit-document-action" class="action-select" name="action">
                  <option value="">Choose action</option>
                  <option value="partner_webhook_completed">Validate webhook</option>
                  <option value="partner_webhook_rejected">Invalidate webhook</option>
                  {% for value, label in pipeline_actions %}
                  <option value="{{ value }}">{{ label }}</option>
                  {% endfor %}
                </select>
                <button class="btn btn-primary" type="submit">Apply action</button>
              </div>
            </div>
            <table class="admin-table">
              <thead>
                <tr>
                  <th class="select-column">
                    <input type="checkbox" data-select-all aria-label="Select all documents">
                  </th>
                  <th>Document</th>
                  <th>Status</th>
                  <th>Owner</th>
                  <th>Organization</th>
                  <th>External job</th>
                  <th>Debug</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {% for row in rows %}
                <tr>
                  <td><input class="row-selector" type="checkbox" name="rowid" value="{{ row.id }}" data-row-selector></td>
                  <td><a href="/documents/{{ row.id }}">{{ row.original_filename }}</a></td>
                  <td><a href="/test-cockpit?status={{ row.status }}"><code>{{ row.status }}</code></a></td>
                  <td><a href="/test-cockpit?owner_user_id={{ row.owner_user_id }}">{{ row.owner_email }}</a></td>
                  <td><a href="/test-cockpit?org_id={{ row.org_id }}">{{ row.organization_name }}</a></td>
                  <td>{{ row.external_job_id or "-" }}</td>
                  <td><a href="/documents/{{ row.id }}">detail/steps</a></td>
                  <td>
                    <a href="/documents/{{ row.id }}/actions">Webhook</a>
                    <span class="row-links">
                      <a href="/documents/{{ row.id }}">detail</a>
                    </span>
                  </td>
                </tr>
                {% endfor %}
                {% if not rows %}
                <tr><td colspan="8">No document matches these filters.</td></tr>
                {% endif %}
              </tbody>
            </table>
          </form>
        </section>
        """,
        all_users=all_users,
        filters=filters,
        organizations=organizations,
        pipeline_actions=PIPELINE_RELAUNCH_ACTIONS,
        render_document_filters=_render_document_filters,
        rows=rows,
        users=users,
    )


def _render_document_filters(
    filters: AdminDocumentFilters,
    organizations,
    users,
    action: str,
    *,
    submit_label: str = "Apply filters",
) -> str:
    return render_template_string(
        """
        <form class="filters" method="get" action="{{ action }}">
          <div class="filter-grid">
            <label>
              Organization
              <select name="org_id">
                <option value="">All organizations</option>
                {% for org in organizations %}
                <option value="{{ org.id }}" {% if filters.org_id == org.id %}selected{% endif %}>{{ org.name }}</option>
                {% endfor %}
              </select>
            </label>
            <label>
              Owner
              <select name="owner_user_id">
                <option value="">All users</option>
                {% for user in users %}
                <option value="{{ user.id }}" {% if filters.owner_user_id == user.id %}selected{% endif %}>{{ user.email }}</option>
                {% endfor %}
              </select>
            </label>
            <label>
              Status
              <select name="status">
                <option value="">All statuses</option>
                {% for status in statuses %}
                <option value="{{ status }}" {% if filters.status == status %}selected{% endif %}>{{ status }}</option>
                {% endfor %}
              </select>
            </label>
            <label>
              Search
              <input type="search" name="q" value="{{ filters.q }}" placeholder="filename, job, owner, error">
            </label>
            <label>
              Limit
              <input type="number" name="limit" min="1" max="500" value="{{ filters.limit }}">
            </label>
          </div>
          <div class="filter-actions">
            <button class="btn btn-primary" type="submit">{{ submit_label }}</button>
            <a class="btn btn-secondary" href="{{ action }}">Clear</a>
          </div>
        </form>
        """,
        action=action,
        filters=filters,
        organizations=organizations,
        statuses=[status.value for status in DocumentStatus],
        submit_label=submit_label,
        users=users,
    )


def _render_page(*, title: str, body: str, auto_refresh_seconds: int = 0) -> str:
    return render_template_string(
        """
        <!doctype html>
        <html lang="en">
          <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>{{ title }} — Primmo Admin</title>
            {% if auto_refresh_seconds > 0 %}
            <meta http-equiv="refresh" content="{{ auto_refresh_seconds }}">
            {% endif %}
            <link rel="preconnect" href="https://fonts.googleapis.com">
            <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
            <link href="https://fonts.googleapis.com/css2?family=DM+Mono:ital,wght@0,400;0,500;1,400&family=Geist:wght@300;400;500;600&display=swap" rel="stylesheet">
            <style>
              :root {
                --bg: #0d1117;
                --surface: #161b22;
                --surface-2: #1c2128;
                --border: #30363d;
                --border-muted: #21262d;
                --text: #e6edf3;
                --text-muted: #8b949e;
                --text-subtle: #6e7681;
                --accent: #58a6ff;
                --accent-hover: #79b8ff;
                --green: #3fb950;
                --amber: #d29922;
                --red: #f85149;
                --font-ui: 'Geist', ui-sans-serif, system-ui, sans-serif;
                --font-mono: 'DM Mono', ui-monospace, 'SF Mono', monospace;
                --radius: 6px;
              }
              *, *::before, *::after { box-sizing: border-box; }
              html { color-scheme: dark; }
              body {
                background: var(--bg);
                color: var(--text);
                font-family: var(--font-ui);
                font-size: 14px;
                line-height: 1.5;
                margin: 0;
              }
              a { color: var(--accent); text-decoration: none; }
              a:hover { color: var(--accent-hover); text-decoration: underline; }
              h1 { font-size: 20px; font-weight: 600; margin: 0 0 20px; }
              h2 { font-size: 15px; font-weight: 600; margin: 0 0 12px; }
              code {
                background: rgba(110,118,129,.2);
                border-radius: 4px;
                font-family: var(--font-mono);
                font-size: 12px;
                padding: 2px 6px;
              }
              code.status-ready    { background: rgba(63,185,80,.15);  color: var(--green); }
              code.status-failed   { background: rgba(248,81,73,.15);  color: var(--red); }
              code.status-processing      { background: rgba(88,166,255,.15); color: var(--accent); }
              code.status-waiting_partner { background: rgba(210,153,34,.2);  color: var(--amber); }
              code.status-pending         { background: rgba(139,148,158,.12); color: var(--text-muted); }
              code.status-completed { background: rgba(63,185,80,.15);  color: var(--green); }
              code.status-rejected  { background: rgba(248,81,73,.15);  color: var(--red); }
              code.status-skipped   { background: rgba(139,148,158,.12); color: var(--text-muted); }
              pre {
                background: #010409;
                border: 1px solid var(--border);
                border-radius: var(--radius);
                color: #e6edf3;
                font-family: var(--font-mono);
                font-size: 12px;
                margin: 0;
                max-width: 560px;
                overflow: auto;
                padding: 12px;
                white-space: pre-wrap;
                word-break: break-word;
              }
              header {
                background: var(--surface);
                border-bottom: 1px solid var(--border);
                padding: 0 24px;
                position: sticky;
                top: 0;
                z-index: 100;
              }
              .header-inner {
                align-items: center;
                display: flex;
                flex-wrap: wrap;
                gap: 0;
                justify-content: space-between;
                min-height: 48px;
              }
              .brand {
                align-items: center;
                color: var(--text-muted);
                display: flex;
                font-family: var(--font-mono);
                font-size: 12px;
                font-weight: 500;
                gap: 6px;
                letter-spacing: .04em;
                margin-right: 24px;
                text-transform: uppercase;
              }
              .brand-dot {
                animation: pulse-dot 3s ease-in-out infinite;
                background: var(--green);
                border-radius: 50%;
                display: inline-block;
                height: 6px;
                width: 6px;
              }
              @keyframes pulse-dot {
                0%, 100% { opacity: 1; }
                50% { opacity: 0.4; }
              }
              nav.topnav {
                display: flex;
                flex-wrap: wrap;
                gap: 0;
              }
              nav.topnav a {
                border-bottom: 2px solid transparent;
                color: var(--text-muted);
                display: block;
                font-size: 13px;
                font-weight: 500;
                padding: 14px 12px;
                transition: color .12s, border-color .12s;
              }
              nav.topnav a:hover {
                color: var(--text);
                text-decoration: none;
              }
              nav.topnav a.nav-highlight {
                border-bottom-color: var(--accent);
                color: var(--accent);
              }
              nav.topnav a.nav-highlight:hover { color: var(--accent-hover); }
              {% if auto_refresh_seconds > 0 %}
              .refresh-badge {
                align-items: center;
                background: rgba(63,185,80,.1);
                border: 1px solid rgba(63,185,80,.2);
                border-radius: 999px;
                color: var(--green);
                display: inline-flex;
                font-family: var(--font-mono);
                font-size: 11px;
                gap: 5px;
                padding: 3px 9px;
              }
              .refresh-dot {
                animation: pulse-dot 1.5s ease-in-out infinite;
                background: currentColor;
                border-radius: 50%;
                display: inline-block;
                height: 5px;
                width: 5px;
              }
              {% endif %}
              main {
                margin: 0 auto;
                max-width: 1400px;
                padding: 24px 24px 48px;
              }
              .intro { color: var(--text-muted); margin: -8px 0 20px; }
              .panel {
                background: var(--surface);
                border: 1px solid var(--border);
                border-radius: var(--radius);
                margin-bottom: 16px;
                padding: 16px;
              }
              .section-head {
                align-items: center;
                display: flex;
                flex-wrap: wrap;
                gap: 12px;
                justify-content: space-between;
                margin-bottom: 12px;
              }
              .details {
                background: var(--surface);
                border: 1px solid var(--border);
                border-radius: var(--radius);
                margin-bottom: 16px;
                padding: 16px;
              }
              dl {
                display: grid;
                gap: 16px;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                margin: 0;
              }
              dt {
                color: var(--text-subtle);
                font-family: var(--font-mono);
                font-size: 11px;
                font-weight: 500;
                letter-spacing: .05em;
                text-transform: uppercase;
              }
              dd { margin: 4px 0 0; }
              .metric-grid {
                display: grid;
                gap: 12px;
                grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
                margin-bottom: 16px;
              }
              .metric-card {
                background: var(--surface);
                border: 1px solid var(--border);
                border-radius: var(--radius);
                color: var(--text);
                display: block;
                padding: 14px 16px;
                text-decoration: none;
                transition: border-color .15s;
              }
              .metric-card:hover { border-color: var(--accent); text-decoration: none; }
              .metric-card span {
                color: var(--text-muted);
                display: block;
                font-size: 11px;
                font-weight: 600;
                letter-spacing: .04em;
                text-transform: uppercase;
              }
              .metric-card strong {
                display: block;
                font-size: 26px;
                font-weight: 600;
                margin-top: 4px;
              }
              .metric-card.accent { border-color: var(--amber); }
              .metric-card.accent strong { color: var(--amber); }
              table {
                background: var(--surface);
                border: 1px solid var(--border);
                border-collapse: collapse;
                border-radius: var(--radius);
                overflow: hidden;
                width: 100%;
              }
              .model-list table { border: 0; border-radius: 0; }
              th, td {
                border-bottom: 1px solid var(--border-muted);
                font-size: 13px;
                padding: 9px 12px;
                text-align: left;
                vertical-align: top;
              }
              th {
                background: rgba(255,255,255,.025);
                color: var(--text-muted);
                font-family: var(--font-mono);
                font-size: 11px;
                font-weight: 500;
                letter-spacing: .04em;
                text-transform: uppercase;
              }
              tr:last-child td { border-bottom: 0; }
              tr:hover td { background: rgba(255,255,255,.02); }
              .select-column { width: 38px; }
              .row-links { display: flex; gap: 8px; margin-top: 4px; }
              .row-links a { color: var(--text-subtle); font-size: 11px; }
              .filters {
                background: var(--surface);
                border: 1px solid var(--border);
                border-radius: var(--radius);
                margin-bottom: 16px;
                padding: 16px;
              }
              .filter-grid {
                display: grid;
                gap: 12px;
                grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
              }
              .filter-grid.compact { grid-template-columns: minmax(180px, 320px); }
              .filter-grid label, .table-filter {
                color: var(--text-muted);
                display: grid;
                font-family: var(--font-mono);
                font-size: 11px;
                font-weight: 500;
                gap: 6px;
                letter-spacing: .04em;
                text-transform: uppercase;
              }
              .filter-grid input,
              .filter-grid select,
              .table-filter input,
              .form-field select,
              .form-field input[type="file"],
              .form-field input[type="number"],
              .form-field input[type="text"] {
                background: var(--bg);
                border: 1px solid var(--border);
                border-radius: var(--radius);
                color: var(--text);
                font: inherit;
                padding: 7px 10px;
                transition: border-color .15s;
              }
              .filter-grid input:focus,
              .filter-grid select:focus,
              .table-filter input:focus,
              .form-field select:focus,
              .form-field input:focus { border-color: var(--accent); outline: none; }
              select option { background: var(--surface); }
              .filter-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
              .table-filter { margin-bottom: 12px; max-width: 320px; }
              button, .btn {
                align-items: center;
                border: 1px solid transparent;
                border-radius: var(--radius);
                cursor: pointer;
                display: inline-flex;
                font: inherit;
                font-size: 13px;
                font-weight: 600;
                padding: 7px 14px;
                text-decoration: none;
                transition: background .12s, border-color .12s;
              }
              .btn-primary { background: #1f6feb; border-color: rgba(240,246,252,.1); color: #fff; }
              .btn-primary:hover { background: #388bfd; text-decoration: none; }
              .btn-secondary { background: rgba(240,246,252,.06); border-color: var(--border); color: var(--text); }
              .btn-secondary:hover { background: rgba(240,246,252,.1); border-color: rgba(240,246,252,.2); text-decoration: none; }
              .btn-danger { background: rgba(248,81,73,.12); border-color: rgba(248,81,73,.35); color: var(--red); }
              .btn-danger:hover { background: rgba(248,81,73,.22); text-decoration: none; }
              .model-list {
                background: var(--surface);
                border: 1px solid var(--border);
                border-radius: var(--radius);
                overflow: hidden;
              }
              .model-list-toolbar {
                align-items: center;
                border-bottom: 1px solid var(--border);
                display: flex;
                flex-wrap: wrap;
                gap: 12px;
                justify-content: space-between;
                padding: 12px 14px;
              }
              .action-controls { align-items: center; display: flex; flex-wrap: wrap; gap: 8px; }
              .action-select {
                background: var(--bg);
                border: 1px solid var(--border);
                border-radius: var(--radius);
                color: var(--text);
                font: inherit;
                font-size: 13px;
                min-width: 220px;
                padding: 7px 10px;
              }
              .selection-count {
                background: rgba(88,166,255,.12);
                border: 1px solid rgba(88,166,255,.25);
                border-radius: 999px;
                color: var(--accent);
                display: inline-block;
                font-family: var(--font-mono);
                font-size: 11px;
                font-weight: 600;
                margin-left: 6px;
                padding: 2px 8px;
              }
              .action-buttons { display: flex; flex-wrap: wrap; gap: 10px; padding: 14px 16px; }
              .action-panel { margin-bottom: 20px; }
              .admin-form {
                background: var(--surface);
                border: 1px solid var(--border);
                border-radius: var(--radius);
                max-width: 640px;
                padding: 20px;
              }
              .form-field { display: grid; gap: 6px; margin-bottom: 16px; }
              .form-field label {
                color: var(--text-muted);
                font-family: var(--font-mono);
                font-size: 11px;
                font-weight: 500;
                letter-spacing: .04em;
                text-transform: uppercase;
              }
              input[type="checkbox"] { accent-color: var(--accent); height: 15px; width: 15px; }
              .page-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; }
              .dashboard-grid {
                display: grid;
                gap: 16px;
                grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
                margin-bottom: 16px;
              }
              .sr-only {
                clip: rect(0,0,0,0); border: 0; height: 1px; margin: -1px;
                overflow: hidden; padding: 0; position: absolute; white-space: nowrap; width: 1px;
              }
              .muted { color: var(--text-muted); font-size: 13px; }
              /* Pipeline track */
              .pipeline-track {
                display: flex;
                flex-wrap: wrap;
                gap: 0;
                margin-bottom: 20px;
              }
              .pipeline-step {
                background: var(--surface);
                border: 1px solid var(--border);
                flex: 1;
                font-size: 12px;
                min-width: 100px;
                padding: 10px 14px;
                position: relative;
                text-align: center;
              }
              .pipeline-step + .pipeline-step { border-left: 0; }
              .pipeline-step:first-child { border-radius: var(--radius) 0 0 var(--radius); }
              .pipeline-step:last-child { border-radius: 0 var(--radius) var(--radius) 0; }
              .pipeline-step-name { font-family: var(--font-mono); font-weight: 500; }
              .pipeline-step-status { font-size: 11px; font-weight: 600; letter-spacing: .03em; text-transform: uppercase; margin-top: 2px; }
              .pipeline-step.step-pending { color: var(--text-subtle); }
              .pipeline-step.step-processing { background: rgba(88,166,255,.08); border-color: rgba(88,166,255,.3); color: var(--accent); }
              .pipeline-step.step-completed { background: rgba(63,185,80,.08); border-color: rgba(63,185,80,.3); color: var(--green); }
              .pipeline-step.step-failed { background: rgba(248,81,73,.08); border-color: rgba(248,81,73,.3); color: var(--red); }
              /* Workflow checklist */
              .workflow-list { counter-reset: step; list-style: none; margin: 0 0 16px; padding: 0; }
              .workflow-list li {
                align-items: flex-start;
                color: var(--text-muted);
                counter-increment: step;
                display: flex;
                font-size: 13px;
                gap: 10px;
                padding: 5px 0;
              }
              .workflow-list li::before {
                background: var(--surface-2);
                border: 1px solid var(--border);
                border-radius: 50%;
                color: var(--text-subtle);
                content: counter(step);
                flex-shrink: 0;
                font-family: var(--font-mono);
                font-size: 10px;
                font-weight: 600;
                height: 20px;
                line-height: 18px;
                text-align: center;
                width: 20px;
              }
            </style>
          </head>
          <body>
            <header>
              <div class="header-inner">
                <span class="brand">
                  <span class="brand-dot"></span>
                  Primmo Admin
                </span>
                <nav class="topnav">
                  <a class="nav-highlight" href="/test-cockpit">Test Cockpit</a>
                  <a href="/documents/new">Add Documents</a>
                </nav>
                {% if auto_refresh_seconds > 0 %}
                <span class="refresh-badge">
                  <span class="refresh-dot"></span>
                  auto-refresh {{ auto_refresh_seconds }}s
                </span>
                {% endif %}
              </div>
            </header>
            <main>{{ body | safe }}</main>
            <script>
              (function () {
                // Status badge colorization
                Array.prototype.slice.call(document.querySelectorAll('code')).forEach(function(el) {
                  var text = el.textContent.trim().toLowerCase().replace(/-/g, '_');
                  var statuses = ['ready','failed','processing','waiting_partner','pending','completed','rejected','skipped'];
                  for (var i = 0; i < statuses.length; i++) {
                    if (text === statuses[i]) { el.classList.add('status-' + statuses[i]); break; }
                  }
                });
                // Table filter
                Array.prototype.slice.call(document.querySelectorAll('[data-table-filter]')).forEach(function(input) {
                  var table = document.getElementById(input.dataset.tableFilter);
                  if (!table) return;
                  var rows = Array.prototype.slice.call(table.querySelectorAll('tbody tr'));
                  input.addEventListener('input', function() {
                    var q = input.value.toLowerCase();
                    rows.forEach(function(row) {
                      row.style.display = row.textContent.toLowerCase().indexOf(q) === -1 ? 'none' : '';
                    });
                  });
                });
                // Select all
                var selectAll = document.querySelector('[data-select-all]');
                var rowSelectors = Array.prototype.slice.call(document.querySelectorAll('[data-row-selector]'));
                var selectedCount = document.querySelector('[data-selected-count]');
                function enabledRows() { return rowSelectors.filter(function(c) { return !c.disabled; }); }
                function checkedRows() { return enabledRows().filter(function(c) { return c.checked; }); }
                function updateSelectionState() {
                  var enabled = enabledRows(), checked = checkedRows();
                  if (selectedCount) selectedCount.textContent = checked.length + ' selected';
                  if (selectAll) {
                    selectAll.checked = enabled.length > 0 && checked.length === enabled.length;
                    selectAll.indeterminate = checked.length > 0 && checked.length < enabled.length;
                  }
                }
                if (selectAll) {
                  selectAll.addEventListener('change', function() {
                    enabledRows().forEach(function(c) { c.checked = selectAll.checked; });
                    updateSelectionState();
                  });
                  rowSelectors.forEach(function(c) { c.addEventListener('change', updateSelectionState); });
                  updateSelectionState();
                }
                // Confirm dialogs
                Array.prototype.slice.call(document.querySelectorAll('[data-confirm-message]')).forEach(function(form) {
                  form.addEventListener('submit', function(event) {
                    var action = form.querySelector('select[name="action"]');
                    if (action && (checkedRows().length === 0 || !action.value)) {
                      event.preventDefault();
                      window.alert('Select at least one document and one action.');
                      return;
                    }
                    if (!window.confirm(form.dataset.confirmMessage)) event.preventDefault();
                  });
                });
              })();
            </script>
          </body>
        </html>
        """,
        title=title,
        body=body,
        auto_refresh_seconds=auto_refresh_seconds,
    )


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.isoformat()


def _document_filters_from_request(
    *,
    default_status: str = "",
    default_limit: int = 100,
) -> AdminDocumentFilters:
    raw_status = request.args.get("status")
    return AdminDocumentFilters(
        org_id=_optional_uuid(request.args.get("org_id")),
        owner_user_id=_optional_uuid(request.args.get("owner_user_id")),
        status=(raw_status if raw_status is not None else default_status).strip(),
        q=_query_value("q"),
        limit=_parse_limit(request.args.get("limit"), default=default_limit),
    )


def _query_value(name: str) -> str:
    return (request.args.get(name) or "").strip()


def _optional_uuid(raw_value: str | None) -> UUID | None:
    if raw_value is None or not raw_value.strip():
        return None
    return _parse_uuid(raw_value)


def _parse_limit(raw_value: str | None, *, default: int) -> int:
    if raw_value is None or not raw_value.strip():
        return default
    return _parse_bounded_int(raw_value, min_value=1, max_value=500)


def _parse_document_ids(raw_values: list[str]) -> list[UUID]:
    try:
        return [UUID(value) for value in raw_values]
    except ValueError:
        abort(400)


def _pipeline_strategy_from_action(action: str | None) -> PipelineStrategyName | None:
    if action is None or not action.startswith(PIPELINE_RELAUNCH_ACTION_PREFIX):
        return None
    raw_strategy = action.removeprefix(PIPELINE_RELAUNCH_ACTION_PREFIX)
    try:
        return PipelineStrategyName(raw_strategy)
    except ValueError:
        abort(400)


def _parse_uuid(raw_value: str | None) -> UUID:
    if raw_value is None:
        abort(400)
    try:
        return UUID(raw_value)
    except ValueError:
        abort(400)


def _parse_bounded_int(raw_value: str | None, *, min_value: int, max_value: int) -> int:
    try:
        value = int(raw_value or "")
    except ValueError:
        abort(400)
    if value < min_value or value > max_value:
        abort(400)
    return value


def _render_new_documents_form(*, users) -> str:
    return _render_page(
        title="Add documents",
        body=render_template_string(
            """
            <p><a href="/test-cockpit">← Back to Test Cockpit</a></p>
            <h2>Upload PDFs</h2>
            <form class="admin-form" method="post" action="/documents/new" enctype="multipart/form-data">
              <div class="form-field">
                <label for="owner-user-id">User</label>
                <select id="owner-user-id" name="owner_user_id" required>
                  {% for user in users %}
                  <option value="{{ user.id }}">{{ user.email }} - {{ user.organization_name }}</option>
                  {% endfor %}
                </select>
              </div>
              <div class="form-field">
                <label for="document-files">PDF documents</label>
                <input id="document-files" type="file" name="files" accept="application/pdf" multiple required>
              </div>
              <button class="btn btn-primary" type="submit">Create documents and launch pipelines</button>
            </form>

            <h2 class="section-title">Generate fake batch</h2>
            <form class="admin-form" method="post" action="/documents/generate-fake-batch">
              <div class="form-field">
                <label for="organization-name">Organization name</label>
                <input id="organization-name" type="text" name="organization_name" value="Load Test Org" required>
              </div>
              <div class="form-field">
                <label for="user-count">Users to create or reuse</label>
                <input id="user-count" type="number" name="user_count" min="1" max="50" value="50" required>
              </div>
              <div class="form-field">
                <label for="document-count">Fake documents to generate</label>
                <input id="document-count" type="number" name="document_count" min="1" max="1000" value="200" required>
              </div>
              <div class="form-field">
                <label for="filename-prefix">Filename prefix</label>
                <input id="filename-prefix" type="text" name="filename_prefix" value="load-test-lease" required>
              </div>
              <button class="btn btn-primary" type="submit">Generate fake documents and launch pipelines</button>
            </form>
            """,
            users=users,
        ),
    )


def _enqueue_uploaded_documents(
    results: list[AdminDocumentUploadResult],
    pipeline,
) -> list[AdminDocumentUploadResult]:
    queued_results = []
    for result in results:
        if result.document_id is None or result.status != "uploaded":
            queued_results.append(result)
            continue
        try:
            task_id = pipeline.enqueue_full_pipeline(result.document_id)
        except Exception as exc:  # pragma: no cover - defensive local admin feedback
            queued_results.append(AdminDocumentUploadActions.mark_enqueue_failed(result, error=exc))
            continue
        queued_results.append(AdminDocumentUploadActions.mark_queued(result, task_id=task_id))
    return queued_results


def _enqueue_pipeline_relaunches(
    results: list[AdminPipelineActionResult],
    pipeline,
) -> list[AdminPipelineActionResult]:
    queued_results = []
    for result in results:
        if result.status != "prepared":
            queued_results.append(result)
            continue
        try:
            task_id = pipeline.enqueue(result.document_id, strategy=result.strategy)
        except Exception as exc:  # pragma: no cover - defensive local admin feedback
            queued_results.append(AdminPipelineActions.mark_enqueue_failed(result, error=exc))
            continue
        queued_results.append(AdminPipelineActions.mark_queued(result, task_id=task_id))
    return queued_results


def _render_document_upload_results(results: list[AdminDocumentUploadResult]) -> str:
    created_count = sum(1 for result in results if result.document_id is not None)
    return _render_page(
        title="Documents created",
        body=render_template_string(
            """
            <p><a href="/test-cockpit">← Back to Test Cockpit</a></p>
            <p class="intro">{{ created_count }} documents created.</p>
            <table>
              <thead>
                <tr>
                  <th>Filename</th>
                  <th>Owner</th>
                  <th>Status</th>
                  <th>Message</th>
                  <th>Task</th>
                  <th>Storage key</th>
                </tr>
              </thead>
              <tbody>
                {% for result in results %}
                <tr>
                  <td>
                    {% if result.document_id %}
                    <a href="/documents/{{ result.document_id }}">{{ result.filename }}</a>
                    {% else %}
                    {{ result.filename }}
                    {% endif %}
                  </td>
                  <td>{{ result.owner_email }}</td>
                  <td><code>{{ result.status }}</code></td>
                  <td>{{ result.message }}</td>
                  <td>{{ result.task_id or "-" }}</td>
                  <td>{% if result.storage_key %}<code>{{ result.storage_key }}</code>{% else %}-{% endif %}</td>
                </tr>
                {% endfor %}
                {% if not results %}
                <tr>
                  <td colspan="6">No files selected.</td>
                </tr>
                {% endif %}
              </tbody>
            </table>
            """,
            results=results,
            created_count=created_count,
        ),
    )


def _render_pipeline_relaunch_results(results: list[AdminPipelineActionResult]) -> str:
    return _render_page(
        title="Pipeline relaunch results",
        body=render_template_string(
            """
            <p class="intro">
              Admin-only action: resets the durable state required by the selected strategy,
              then enqueues the matching Celery canvas.
            </p>
            <p><a href="/test-cockpit">← Back to Test Cockpit</a></p>
            <table>
              <thead>
                <tr>
                  <th>Document</th>
                  <th>Strategy</th>
                  <th>Status</th>
                  <th>Message</th>
                  <th>Task</th>
                </tr>
              </thead>
              <tbody>
                {% for result in results %}
                <tr>
                  <td><a href="/documents/{{ result.document_id }}">{{ result.filename }}</a></td>
                  <td><code>{{ result.strategy }}</code></td>
                  <td><code>{{ result.status }}</code></td>
                  <td>{{ result.message }}</td>
                  <td>{{ result.task_id or "-" }}</td>
                </tr>
                {% endfor %}
                {% if not results %}
                <tr>
                  <td colspan="5">No document selected.</td>
                </tr>
                {% endif %}
              </tbody>
            </table>
            """,
            results=results,
        ),
    )


def _render_partner_webhook_results(results) -> str:
    return _render_page(
        title="Partner webhook action results",
        body=render_template_string(
            """
            <p class="intro">
              Test endpoint action: signs the same partner webhook payload used by the demo front,
              then applies the completed webhook transition through the processing service.
            </p>
            <p><a href="/test-cockpit">← Back to Test Cockpit</a></p>
            <table>
              <thead>
                <tr>
                  <th>Document</th>
                  <th>Job</th>
                  <th>Status</th>
                  <th>Message</th>
                  <th>X-Partner-Signature</th>
                  <th>Request body</th>
                </tr>
              </thead>
              <tbody>
                {% for result in results %}
                <tr>
                  <td><a href="/documents/{{ result.document_id }}">{{ result.filename }}</a></td>
                  <td>{{ result.job_id or "-" }}</td>
                  <td><code>{{ result.status }}</code></td>
                  <td>{{ result.message }}</td>
                  <td><code>{{ result.signature or "-" }}</code></td>
                  <td>{% if result.request_body %}<pre>{{ result.request_body }}</pre>{% else %}-{% endif %}</td>
                </tr>
                {% endfor %}
                {% if not results %}
                <tr>
                  <td colspan="6">No document selected.</td>
                </tr>
                {% endif %}
              </tbody>
            </table>
            """,
            results=results,
        ),
    )
