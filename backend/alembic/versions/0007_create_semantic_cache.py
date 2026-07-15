"""create semantic cache table"""

from __future__ import annotations

from alembic import op

revision = "0007_sem_cache"
down_revision = "0006_exact_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE semantic_cache (
            id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            query_embedding      VECTOR(1536) NOT NULL,
            representative_query TEXT NOT NULL,
            answer               TEXT NOT NULL,
            source_doc_ids       UUID[],
            hit_count            INT NOT NULL DEFAULT 1,
            last_used_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX semantic_cache_embedding_idx ON semantic_cache
            USING hnsw (query_embedding vector_cosine_ops)
        """
    )
    op.execute("CREATE INDEX semantic_cache_last_used_idx ON semantic_cache (last_used_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS semantic_cache_last_used_idx")
    op.execute("DROP INDEX IF EXISTS semantic_cache_embedding_idx")
    op.execute("DROP TABLE IF EXISTS semantic_cache")
