"""make a missing semantic_cache.embedding_model loud instead of silently wrong

`semantic_cache.embedding_model` exists for exactly one reason: to stop a vector produced
by one embedding model being compared against a vector produced by another. Cosine distance
between two different embedding spaces is a number with no meaning, and a semantic cache
that returns such a "hit" serves a stale answer to an unrelated question.

The column shipped with `DEFAULT 'text-embedding-3-small'`, which defeats that guarantee.
Any INSERT that omits the column does not fail — it silently labels its vectors as OpenAI's
model. On a Gemini deployment that means Gemini vectors filed under an OpenAI label, and the
next lookup happily compares across spaces. The failure is invisible: no error, no log, just
occasional wrong answers served from cache.

Dropping the default converts that silent mislabel into a NOT NULL violation: loud,
immediate, and impossible to ship. `chunks.embedding_model` already has no default, which is
the correct shape; this brings the cache in line with it.

Existing rows are left alone — they were written by `write_semantic_cache`, which has always
passed the column explicitly, so their labels are already correct.
"""

from __future__ import annotations

from alembic import op

revision = "0016_sem_cache_no_default"
down_revision = "0015_trace_decisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE semantic_cache ALTER COLUMN embedding_model DROP DEFAULT")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE semantic_cache "
        "ALTER COLUMN embedding_model SET DEFAULT 'text-embedding-3-small'"
    )
