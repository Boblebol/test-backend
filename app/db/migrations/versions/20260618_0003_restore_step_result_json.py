"""restore processing step result_json

Revision ID: 20260618_0003
Revises: 20260618_0002
Create Date: 2026-06-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260618_0003"
down_revision: str | None = "20260618_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE document_processing_steps ADD COLUMN IF NOT EXISTS result_json JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE document_processing_steps DROP COLUMN IF EXISTS result_json")
