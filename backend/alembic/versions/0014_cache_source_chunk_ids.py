"""store source chunk ids on cached answers

A cached answer carries sentence-end superscripts, so a cache hit must be able
to rebuild the same reference list the original miss returned. The caches only
recorded document ids, which is too coarse to resolve page/section metadata.
"""

from __future__ import annotations

from alembic import op

revision = "0014_cache_chunk_ids"
down_revision = "0013_correctives"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE exact_cache ADD COLUMN source_chunk_ids UUID[] NOT NULL DEFAULT '{}'")
    op.execute("ALTER TABLE semantic_cache ADD COLUMN source_chunk_ids UUID[] NOT NULL DEFAULT '{}'")


def downgrade() -> None:
    op.execute("ALTER TABLE semantic_cache DROP COLUMN IF EXISTS source_chunk_ids")
    op.execute("ALTER TABLE exact_cache DROP COLUMN IF EXISTS source_chunk_ids")
