"""create chat session and message tables"""

from __future__ import annotations

from alembic import op

revision = "0005_chat"
down_revision = "0004_page_images"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE chat_sessions (
            id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_ref       TEXT,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_active_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE chat_messages (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id       UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
            role             TEXT NOT NULL,
            content          TEXT NOT NULL,
            source_chunk_ids UUID[],
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX chat_messages_session_idx ON chat_messages (session_id, created_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS chat_messages_session_idx")
    op.execute("DROP TABLE IF EXISTS chat_messages")
    op.execute("DROP TABLE IF EXISTS chat_sessions")
