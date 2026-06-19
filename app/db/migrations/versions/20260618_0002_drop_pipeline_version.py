"""drop unused pipeline execution columns

Revision ID: 20260618_0002
Revises: 20260614_0001
Create Date: 2026-06-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260618_0002"
down_revision: str | None = "20260614_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS pipeline_version")
    op.execute("ALTER TABLE document_processing_steps DROP COLUMN IF EXISTS celery_task_id")
    op.execute("ALTER TABLE document_processing_steps DROP COLUMN IF EXISTS started_at")
    op.execute("ALTER TABLE document_processing_steps DROP COLUMN IF EXISTS finished_at")


def downgrade() -> None:
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS pipeline_version INTEGER NOT NULL DEFAULT 1")
    op.execute("ALTER TABLE document_processing_steps ADD COLUMN IF NOT EXISTS celery_task_id VARCHAR(255)")
    op.execute("ALTER TABLE document_processing_steps ADD COLUMN IF NOT EXISTS started_at TIMESTAMP WITH TIME ZONE")
    op.execute("ALTER TABLE document_processing_steps ADD COLUMN IF NOT EXISTS finished_at TIMESTAMP WITH TIME ZONE")
