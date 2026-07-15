"""add client_ip to query audit log"""

from __future__ import annotations

from alembic import op

revision = "0012_client_ip"
down_revision = "0011_anomaly"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE query_audit_log ADD COLUMN client_ip INET")


def downgrade() -> None:
    op.execute("ALTER TABLE query_audit_log DROP COLUMN IF EXISTS client_ip")
