"""create query audit log table"""

from __future__ import annotations

from alembic import op

revision = "0008_query_audit"
down_revision = "0007_sem_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE query_audit_log (
            id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id               UUID REFERENCES chat_sessions(id),
            idempotency_key          TEXT UNIQUE,
            query                    TEXT NOT NULL,
            cache_status             TEXT,
            cost_category            TEXT,
            retrieved_chunk_ids      UUID[],
            reranked                 BOOLEAN DEFAULT false,
            retrieval_mode           TEXT,
            generation_model         TEXT,
            grounded                 BOOLEAN,
            input_validation_status  TEXT NOT NULL DEFAULT 'passed',
            output_filter_status     TEXT NOT NULL DEFAULT 'passed',
            output_filter_reason     TEXT,
            latency_ms               INT,
            token_input              INT,
            token_output             INT,
            cost_usd                 NUMERIC(10,6),
            created_at               TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX query_audit_log_idempotency_key_idx
            ON query_audit_log (idempotency_key)
            WHERE idempotency_key IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS query_audit_log_idempotency_key_idx")
    op.execute("DROP TABLE IF EXISTS query_audit_log")
