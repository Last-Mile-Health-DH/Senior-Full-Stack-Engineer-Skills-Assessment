"""create exact cache table"""

from __future__ import annotations

from alembic import op

revision = "0006_exact_cache"
down_revision = "0005_chat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE exact_cache (
            query_hash     CHAR(64) PRIMARY KEY,
            answer         TEXT NOT NULL,
            source_doc_ids UUID[],
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at     TIMESTAMPTZ NOT NULL
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS exact_cache")
