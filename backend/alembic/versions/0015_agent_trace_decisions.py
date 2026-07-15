"""record agent decisions and scores, not just tool calls

`agent_trace_log` only recorded tool invocations. The decisions that actually determine an
answer — which model the router picked, which chunking strategy the ingestion agent chose,
how confident the reranker was — were invisible, so an audit could see WHAT ran but never
WHY it ran that way.
"""

from __future__ import annotations

from alembic import op

revision = "0015_trace_decisions"
down_revision = "0014_cache_chunk_ids"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Which agent in the mesh emitted this row (orchestrator, retrieval_agent,
    # ingestion_agent, model_router, reranker). `agent_name` was free text per tool.
    op.execute("ALTER TABLE agent_trace_log ADD COLUMN agent_id TEXT")
    # 'tool_call' (the existing rows) | 'decision' | 'score'.
    op.execute(
        "ALTER TABLE agent_trace_log ADD COLUMN event_type TEXT NOT NULL DEFAULT 'tool_call'"
    )
    # Reranker relevance / retrieval confidence, so end-to-end quality is queryable.
    op.execute("ALTER TABLE agent_trace_log ADD COLUMN score DOUBLE PRECISION")

    # The hot query is "replay everything that happened for this one question", in order.
    # Migration 0009 already created `agent_trace_log_session_idx` on (session_id) alone, so
    # these composite indexes need distinct names — reusing that name is a DuplicateTable
    # error that crash-loops the container on startup, because the entrypoint migrates.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS agent_trace_log_query_chain_idx
        ON agent_trace_log (query_audit_log_id, created_at)
        WHERE query_audit_log_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS agent_trace_log_session_chain_idx
        ON agent_trace_log (session_id, created_at)
        WHERE session_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS agent_trace_log_session_chain_idx")
    op.execute("DROP INDEX IF EXISTS agent_trace_log_query_chain_idx")
    op.execute("ALTER TABLE agent_trace_log DROP COLUMN IF EXISTS score")
    op.execute("ALTER TABLE agent_trace_log DROP COLUMN IF EXISTS event_type")
    op.execute("ALTER TABLE agent_trace_log DROP COLUMN IF EXISTS agent_id")
