"""create anomaly flag table"""

from __future__ import annotations

from alembic import op

revision = "0011_anomaly"
down_revision = "0010_grades_view"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE anomaly_flag (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            metric_name     TEXT NOT NULL,
            hour_of_day     SMALLINT NOT NULL CHECK (hour_of_day BETWEEN 0 AND 23),
            observed_value  NUMERIC,
            baseline_mean   NUMERIC,
            baseline_stddev NUMERIC,
            z_score         NUMERIC,
            window_start    TIMESTAMPTZ NOT NULL,
            window_end      TIMESTAMPTZ NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX anomaly_flag_metric_idx ON anomaly_flag (metric_name, created_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS anomaly_flag_metric_idx")
    op.execute("DROP TABLE IF EXISTS anomaly_flag")
