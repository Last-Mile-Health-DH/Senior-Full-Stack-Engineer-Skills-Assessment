"""create documents table"""

from __future__ import annotations

from alembic import op

revision = "0002_docs"
down_revision = "0001_ext"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE documents (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            filename      TEXT NOT NULL,
            content_hash  CHAR(64) NOT NULL UNIQUE,
            status        TEXT NOT NULL DEFAULT 'processing',
            page_count    INT,
            uploaded_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            metadata      JSONB DEFAULT '{}'::jsonb
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS documents")
