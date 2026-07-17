"""create response grades and agentops summary view"""

from __future__ import annotations

from alembic import op

revision = "0010_grades_view"
down_revision = "0009_agent_trace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE response_grade (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            query_audit_log_id      UUID NOT NULL UNIQUE REFERENCES query_audit_log(id) ON DELETE CASCADE,
            grounding_check_passed  BOOLEAN,
            judge_score             SMALLINT,
            judge_rationale         TEXT,
            sampled                 BOOLEAN NOT NULL DEFAULT false,
            graded_at               TIMESTAMPTZ,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX response_grade_query_audit_log_idx ON response_grade (query_audit_log_id)")
    op.execute(
        """
        CREATE VIEW agentops_summary AS
        SELECT
            qal.id                      AS query_audit_log_id,
            qal.session_id,
            qal.query,
            qal.cache_status,
            qal.cost_category,
            qal.retrieval_mode,
            qal.generation_model,
            qal.grounded,
            qal.input_validation_status,
            qal.output_filter_status,
            qal.output_filter_reason,
            qal.latency_ms,
            qal.cost_usd,
            rg.grounding_check_passed   AS graded_grounding_passed,
            rg.judge_score              AS graded_judge_score,
            rg.graded_at,
            array_agg(DISTINCT atl.tool_name) FILTER (WHERE atl.tool_name IS NOT NULL) AS agent_tools_invoked,
            count(DISTINCT atl.id)      AS agent_trace_row_count,
            qal.created_at
        FROM query_audit_log qal
        LEFT JOIN agent_trace_log atl ON atl.query_audit_log_id = qal.id
        LEFT JOIN response_grade rg   ON rg.query_audit_log_id = qal.id
        GROUP BY qal.id, rg.grounding_check_passed, rg.judge_score, rg.graded_at
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS agentops_summary")
    op.execute("DROP INDEX IF EXISTS response_grade_query_audit_log_idx")
    op.execute("DROP TABLE IF EXISTS response_grade")
