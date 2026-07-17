"""create page_images table"""

from __future__ import annotations

from alembic import op

revision = "0004_page_images"
down_revision = "0003_chunks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE page_images (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            document_id  UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            page_number  INT NOT NULL,
            storage_ref  TEXT NOT NULL,
            has_table    BOOLEAN NOT NULL DEFAULT false,
            has_figure   BOOLEAN NOT NULL DEFAULT false,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (document_id, page_number)
        )
        """
    )
    op.execute("CREATE INDEX page_images_document_id_idx ON page_images (document_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS page_images_document_id_idx")
    op.execute("DROP TABLE IF EXISTS page_images")
