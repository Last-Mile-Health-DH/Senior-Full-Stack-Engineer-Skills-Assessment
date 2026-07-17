"""Exact response cache keyed by normalized query hash."""

from __future__ import annotations

import hashlib
import re
import string
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.settings import settings

TRAILING_PUNCTUATION = string.punctuation + " \t\r\n"


@dataclass(slots=True)
class CacheHit:
    answer: str
    source_doc_ids: list[UUID]
    cache_status: str
    similarity: float | None = None


def normalize_query(query: str) -> str:
    """Normalize exact-cache keys: lowercase, collapse spaces, trim punctuation."""
    collapsed = re.sub(r"\s+", " ", query.lower()).strip()
    return collapsed.rstrip(TRAILING_PUNCTUATION)


def query_hash(query: str) -> str:
    return hashlib.sha256(normalize_query(query).encode("utf-8")).hexdigest()


async def lookup_exact_cache(db: AsyncSession, query: str) -> CacheHit | None:
    row = (
        await db.execute(
            text(
                """
                SELECT answer, source_doc_ids
                FROM exact_cache
                WHERE query_hash = :query_hash
                  AND expires_at > now()
                """
            ),
            {"query_hash": query_hash(query)},
        )
    ).mappings().first()
    if row is None:
        return None
    return CacheHit(
        answer=str(row["answer"]),
        source_doc_ids=list(row["source_doc_ids"] or []),
        cache_status="exact_hit",
    )


async def write_exact_cache(
    db: AsyncSession,
    query: str,
    answer: str,
    source_doc_ids: list[UUID],
    eligible: bool,
) -> None:
    """Write an exact-cache row if the answer is cache-eligible."""
    # TODO(BC14): eligible = output_filter_status == "passed"
    if not eligible:
        return
    expires_at = datetime.now(UTC) + timedelta(seconds=settings.exact_cache_ttl_seconds)
    await db.execute(
        text(
            """
            INSERT INTO exact_cache (query_hash, answer, source_doc_ids, expires_at)
            VALUES (:query_hash, :answer, :source_doc_ids, :expires_at)
            ON CONFLICT (query_hash)
            DO UPDATE SET
                answer = EXCLUDED.answer,
                source_doc_ids = EXCLUDED.source_doc_ids,
                created_at = now(),
                expires_at = EXCLUDED.expires_at
            """
        ),
        {
            "query_hash": query_hash(query),
            "answer": answer,
            "source_doc_ids": source_doc_ids,
            "expires_at": expires_at,
        },
    )
