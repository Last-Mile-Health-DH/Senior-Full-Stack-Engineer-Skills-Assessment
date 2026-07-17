"""Cache orchestration helper for BC11 and future chat wiring."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.exact import CacheHit, lookup_exact_cache, write_exact_cache
from app.cache.semantic import lookup_semantic_cache, write_semantic_cache
from app.documents.chunking import EmbeddingClient


@dataclass(slots=True)
class GeneratedAnswer:
    answer: str
    source_doc_ids: list[UUID]


@dataclass(slots=True)
class CachedPipelineResult:
    answer: str
    source_doc_ids: list[UUID]
    cache_status: str
    generated: bool


FullPipelineFn = Callable[[], Awaitable[GeneratedAnswer]]


async def answer_with_cache(
    db: AsyncSession,
    query: str,
    full_pipeline: FullPipelineFn,
    embedding_client: EmbeddingClient | None = None,
) -> CachedPipelineResult:
    """Check exact then semantic cache before running the supplied full pipeline."""
    exact_hit = await lookup_exact_cache(db, query)
    if exact_hit is not None:
        return _from_hit(exact_hit)

    semantic_hit = await lookup_semantic_cache(db, query, embedding_client=embedding_client)
    if semantic_hit is not None:
        return _from_hit(semantic_hit)

    generated = await full_pipeline()
    # TODO(BC14): eligible = output_filter_status == "passed"
    eligible = True
    await write_exact_cache(db, query, generated.answer, generated.source_doc_ids, eligible=eligible)
    await write_semantic_cache(
        db,
        query,
        generated.answer,
        generated.source_doc_ids,
        eligible=eligible,
        embedding_client=embedding_client,
    )
    return CachedPipelineResult(
        answer=generated.answer,
        source_doc_ids=generated.source_doc_ids,
        cache_status="miss",
        generated=True,
    )


def _from_hit(hit: CacheHit) -> CachedPipelineResult:
    return CachedPipelineResult(
        answer=hit.answer,
        source_doc_ids=hit.source_doc_ids,
        cache_status=hit.cache_status,
        generated=False,
    )
