"""create agent trace log table"""

from __future__ import annotations

from alembic import op

revision = "0009_agent_trace"
down_revision = "0008_query_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE agent_trace_log (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_name          TEXT NOT NULL,
            tool_name           TEXT NOT NULL,
            input               JSONB NOT NULL,
            output              JSONB,
            session_id          UUID REFERENCES chat_sessions(id),
            query_audit_log_id  UUID REFERENCES query_audit_log(id),
            document_id         UUID REFERENCES documents(id),
            duration_ms         INT,
            error               TEXT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX agent_trace_log_session_idx ON agent_trace_log (session_id)")
    op.execute("CREATE INDEX agent_trace_log_document_idx ON agent_trace_log (document_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS agent_trace_log_document_idx")
    op.execute("DROP INDEX IF EXISTS agent_trace_log_session_idx")
    op.execute("DROP TABLE IF EXISTS agent_trace_log")
