"""create chunks table and retrieval indexes"""

from __future__ import annotations

from alembic import op

revision = "0003_chunks"
down_revision = "0002_docs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE chunks (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            document_id     UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            chunk_index     INT NOT NULL,
            content         TEXT NOT NULL,
            content_tsv     TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
            content_hash    CHAR(64) NOT NULL,
            section_path    TEXT,
            page_number     INT,
            token_count     INT,
            embedding       VECTOR(1536),
            embedding_model TEXT NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX chunks_embedding_hnsw_idx ON chunks
            USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
        """
    )
    op.execute("CREATE INDEX chunks_tsv_idx ON chunks USING gin (content_tsv)")
    op.execute("CREATE INDEX chunks_document_id_idx ON chunks (document_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS chunks_document_id_idx")
    op.execute("DROP INDEX IF EXISTS chunks_tsv_idx")
    op.execute("DROP INDEX IF EXISTS chunks_embedding_hnsw_idx")
    op.execute("DROP TABLE IF EXISTS chunks")
