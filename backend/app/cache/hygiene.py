"""BC11 cache hygiene job."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.settings import settings


async def cache_hygiene_job(db: AsyncSession) -> None:
    """Expire exact cache, enforce semantic LRU cap, and remove stale doc refs."""
    await db.execute(text("DELETE FROM exact_cache WHERE expires_at < now()"))
    await db.execute(
        text(
            """
            DELETE FROM semantic_cache
            WHERE id IN (
                SELECT id
                FROM semantic_cache
                ORDER BY last_used_at DESC
                OFFSET :max_rows
            )
            """
        ),
        {"max_rows": settings.semantic_cache_max_rows},
    )
    await db.execute(
        text(
            """
            DELETE FROM exact_cache ec
            WHERE ec.source_doc_ids IS NOT NULL
              AND EXISTS (
                  SELECT 1
                  FROM unnest(ec.source_doc_ids) AS source_doc_id(id)
                  WHERE NOT EXISTS (
                      SELECT 1 FROM documents d WHERE d.id = source_doc_id.id
                  )
              )
            """
        )
    )
    await db.execute(
        text(
            """
            DELETE FROM semantic_cache sc
            WHERE sc.source_doc_ids IS NOT NULL
              AND EXISTS (
                  SELECT 1
                  FROM unnest(sc.source_doc_ids) AS source_doc_id(id)
                  WHERE NOT EXISTS (
                      SELECT 1 FROM documents d WHERE d.id = source_doc_id.id
                  )
              )
            """
        )
    )
