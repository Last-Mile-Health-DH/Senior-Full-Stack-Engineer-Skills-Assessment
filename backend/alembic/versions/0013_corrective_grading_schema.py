"""add corrective grading, cache scope, and scheduler indexes"""

from __future__ import annotations

from alembic import op

revision = "0013_correctives"
down_revision = "0012_client_ip"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE semantic_cache "
        "ADD COLUMN embedding_model TEXT NOT NULL DEFAULT 'text-embedding-3-small'"
    )
    op.execute("CREATE INDEX semantic_cache_embedding_model_idx ON semantic_cache (embedding_model)")

    op.execute(
        "CREATE INDEX query_audit_log_session_created_idx "
        "ON query_audit_log (session_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX query_audit_log_client_ip_created_idx "
        "ON query_audit_log (client_ip, created_at DESC) "
        "WHERE client_ip IS NOT NULL"
    )

    op.execute("ALTER TABLE response_grade ADD COLUMN judge_model TEXT")
    op.execute("ALTER TABLE response_grade ADD COLUMN judge_temperature NUMERIC")
    op.execute("ALTER TABLE response_grade ADD COLUMN judge_rubric_version INT")
    op.execute("ALTER TABLE response_grade ADD COLUMN grounding_detail JSONB")

    op.execute("ALTER TABLE anomaly_flag ADD COLUMN cadence TEXT NOT NULL DEFAULT 'hourly'")

    op.execute(
        """
        CREATE TABLE gold_eval_run (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            run_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            git_sha             TEXT NOT NULL,
            corpus_version      TEXT NOT NULL,
            rubric_version      INT NOT NULL,
            judge_model         TEXT NOT NULL,
            judge_temperature   NUMERIC NOT NULL,
            overall_score       NUMERIC NOT NULL,
            category_scores     JSONB NOT NULL DEFAULT '{}'::jsonb,
            pass_rate           NUMERIC NOT NULL,
            question_count      INT NOT NULL,
            skipped_count       INT NOT NULL DEFAULT 0,
            trigger             TEXT NOT NULL,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX gold_eval_run_compat_idx "
        "ON gold_eval_run (corpus_version, rubric_version, judge_model, judge_temperature, created_at DESC)"
    )

    op.execute(
        """
        CREATE TABLE gold_eval_result (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id              UUID NOT NULL REFERENCES gold_eval_run(id) ON DELETE CASCADE,
            question_id         TEXT NOT NULL,
            category            TEXT NOT NULL,
            weight              NUMERIC NOT NULL,
            per_question_score  NUMERIC NOT NULL,
            criterion_scores    JSONB NOT NULL DEFAULT '{}'::jsonb,
            passed              BOOLEAN NOT NULL,
            answer_text         TEXT,
            cited_docs          TEXT[],
            cited_pages         INT[],
            query_audit_log_id  UUID REFERENCES query_audit_log(id) ON DELETE SET NULL,
            judge_rationale     TEXT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX gold_eval_result_run_idx ON gold_eval_result (run_id)")
    op.execute("CREATE INDEX gold_eval_result_category_idx ON gold_eval_result (category, created_at DESC)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS gold_eval_result_category_idx")
    op.execute("DROP INDEX IF EXISTS gold_eval_result_run_idx")
    op.execute("DROP TABLE IF EXISTS gold_eval_result")
    op.execute("DROP INDEX IF EXISTS gold_eval_run_compat_idx")
    op.execute("DROP TABLE IF EXISTS gold_eval_run")

    op.execute("ALTER TABLE anomaly_flag DROP COLUMN IF EXISTS cadence")

    op.execute("ALTER TABLE response_grade DROP COLUMN IF EXISTS grounding_detail")
    op.execute("ALTER TABLE response_grade DROP COLUMN IF EXISTS judge_rubric_version")
    op.execute("ALTER TABLE response_grade DROP COLUMN IF EXISTS judge_temperature")
    op.execute("ALTER TABLE response_grade DROP COLUMN IF EXISTS judge_model")

    op.execute("DROP INDEX IF EXISTS query_audit_log_client_ip_created_idx")
    op.execute("DROP INDEX IF EXISTS query_audit_log_session_created_idx")

    op.execute("DROP INDEX IF EXISTS semantic_cache_embedding_model_idx")
    op.execute("ALTER TABLE semantic_cache DROP COLUMN IF EXISTS embedding_model")
