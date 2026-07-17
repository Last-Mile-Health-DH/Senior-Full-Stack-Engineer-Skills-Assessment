"""BC7 vector, lexical, and hybrid retrieval."""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tracing import traced
from app.documents.chunking import (
    EmbeddingClient,
    get_embedding_client,
    get_embedding_dim,
    validate_embedding_batch,
)
from app.retrieval.models import HybridSearchResult, RetrievalCandidate
from app.settings import settings


async def vector_search(
    db: AsyncSession,
    query: str,
    top_k: int | None = None,
    document_id_filter: list[UUID] | None = None,
    embedding_client: EmbeddingClient | None = None,
    hnsw_ef_search: int | None = None,
) -> list[RetrievalCandidate]:
    """Return pgvector cosine-distance candidates with per-call HNSW tuning."""
    limit = top_k or settings.retrieval_top_k
    query_embedding = await _embed_query(query, embedding_client)
    ef_search = hnsw_ef_search or settings.hnsw_ef_search
    if ef_search <= 0:
        raise ValueError("hnsw_ef_search must be positive")

    await db.execute(text(f"SET LOCAL hnsw.ef_search = {int(ef_search)}"))
    rows = (
        await db.execute(
            text(
                f"""
                SELECT
                    c.id AS chunk_id,
                    c.document_id,
                    d.filename AS document_filename,
                    d.status AS document_status,
                    d.metadata AS document_metadata,
                    c.content,
                    c.page_number,
                    c.section_path,
                    c.embedding <=> CAST(:query_embedding AS vector) AS vector_distance
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE d.status = 'indexed'
                  AND c.embedding IS NOT NULL
                  {_document_filter_sql(document_id_filter)}
                ORDER BY c.embedding <=> CAST(:query_embedding AS vector)
                LIMIT :limit
                """
            ),
            {
                "query_embedding": _vector_literal(query_embedding),
                "limit": limit,
                **_document_filter_params(document_id_filter),
            },
        )
    ).mappings().all()

    candidates: list[RetrievalCandidate] = []
    for rank, row in enumerate(rows, start=1):
        candidates.append(_candidate_from_row(row, vector_rank=rank))
    return candidates


async def lexical_search(
    db: AsyncSession,
    query: str,
    top_k: int | None = None,
    document_id_filter: list[UUID] | None = None,
) -> list[RetrievalCandidate]:
    """Return full-text candidates from the generated ``content_tsv`` column."""
    limit = top_k or settings.retrieval_top_k
    rows = (
        await db.execute(
            text(
                f"""
                SELECT
                    c.id AS chunk_id,
                    c.document_id,
                    d.filename AS document_filename,
                    d.status AS document_status,
                    d.metadata AS document_metadata,
                    c.content,
                    c.page_number,
                    c.section_path,
                    ts_rank_cd(c.content_tsv, plainto_tsquery('english', :query)) AS lexical_score
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE d.status = 'indexed'
                  AND c.content_tsv @@ plainto_tsquery('english', :query)
                  {_document_filter_sql(document_id_filter)}
                ORDER BY lexical_score DESC, c.chunk_index ASC
                LIMIT :limit
                """
            ),
            {
                "query": query,
                "limit": limit,
                **_document_filter_params(document_id_filter),
            },
        )
    ).mappings().all()

    candidates: list[RetrievalCandidate] = []
    for rank, row in enumerate(rows, start=1):
        candidates.append(_candidate_from_row(row, lexical_rank=rank))
    return candidates


def reciprocal_rank_fusion(
    ranked_lists: list[list[UUID]],
    k: int | None = None,
) -> dict[UUID, float]:
    """Fuse ranked IDs with RRF. This is ordering-only, never confidence."""
    rrf_k = k or settings.rrf_k
    scores: dict[UUID, float] = defaultdict(float)
    for ranked in ranked_lists:
        for rank, chunk_id in enumerate(ranked, start=1):
            scores[chunk_id] += 1.0 / (rrf_k + rank)
    return dict(scores)


@traced(agent_name="retrieval_agent")
async def hybrid_search(
    db: AsyncSession,
    query: str,
    top_k: int | None = None,
    document_id_filter: list[UUID] | None = None,
    embedding_client: EmbeddingClient | None = None,
    hybrid_enabled: bool | None = None,
) -> HybridSearchResult:
    """Return vector-only or RRF-fused hybrid candidates."""
    limit = top_k or settings.retrieval_top_k
    use_hybrid = settings.hybrid_search_enabled if hybrid_enabled is None else hybrid_enabled
    vector_candidates = await vector_search(
        db=db,
        query=query,
        top_k=limit,
        document_id_filter=document_id_filter,
        embedding_client=embedding_client,
    )
    if not use_hybrid:
        for candidate in vector_candidates:
            if candidate.vector_rank is not None:
                candidate.fused_score = 1.0 / (settings.rrf_k + candidate.vector_rank)
        return HybridSearchResult(
            candidates=vector_candidates[:limit],
            top_score=vector_candidates[0].fused_score if vector_candidates else 0.0,
            rrf_k=settings.rrf_k,
            hybrid_enabled=False,
        )

    lexical_candidates = await lexical_search(
        db=db,
        query=query,
        top_k=limit,
        document_id_filter=document_id_filter,
    )
    scores = reciprocal_rank_fusion(
        [
            [candidate.chunk_id for candidate in vector_candidates],
            [candidate.chunk_id for candidate in lexical_candidates],
        ],
        k=settings.rrf_k,
    )
    candidates_by_id: dict[UUID, RetrievalCandidate] = {}
    for candidate in [*vector_candidates, *lexical_candidates]:
        existing = candidates_by_id.get(candidate.chunk_id)
        if existing is None:
            candidates_by_id[candidate.chunk_id] = candidate.model_copy()
            existing = candidates_by_id[candidate.chunk_id]
        existing.vector_rank = existing.vector_rank or candidate.vector_rank
        existing.lexical_rank = existing.lexical_rank or candidate.lexical_rank
        existing.vector_distance = existing.vector_distance if existing.vector_distance is not None else candidate.vector_distance
        existing.lexical_score = existing.lexical_score if existing.lexical_score is not None else candidate.lexical_score
        existing.fused_score = scores.get(candidate.chunk_id, 0.0)

    ordered = sorted(
        candidates_by_id.values(),
        key=lambda candidate: (
            -(candidate.fused_score or 0.0),
            candidate.vector_distance if candidate.vector_distance is not None else float("inf"),
            str(candidate.chunk_id),
        ),
    )[:limit]
    return HybridSearchResult(
        candidates=ordered,
        top_score=ordered[0].fused_score if ordered else 0.0,
        rrf_k=settings.rrf_k,
        hybrid_enabled=True,
    )


async def _embed_query(
    query: str,
    embedding_client: EmbeddingClient | None,
) -> list[float]:
    client = embedding_client or get_embedding_client()
    embeddings = await client.embed_texts([query])
    validate_embedding_batch(embeddings, expected_count=1, expected_dim=get_embedding_dim())
    return embeddings[0]


def _candidate_from_row(row: object, **overrides: object) -> RetrievalCandidate:
    mapping = dict(row)
    return RetrievalCandidate(
        chunk_id=mapping["chunk_id"],
        document_id=mapping["document_id"],
        document_filename=str(mapping["document_filename"]),
        document_status=str(mapping["document_status"]),
        document_metadata=dict(mapping["document_metadata"] or {}),
        content=str(mapping["content"]),
        page_number=mapping["page_number"],
        section_path=mapping["section_path"],
        vector_rank=overrides.get("vector_rank"),  # type: ignore[arg-type]
        lexical_rank=overrides.get("lexical_rank"),  # type: ignore[arg-type]
        vector_distance=mapping.get("vector_distance"),
        lexical_score=mapping.get("lexical_score"),
    )


def _document_filter_sql(document_id_filter: list[UUID] | None) -> str:
    if not document_id_filter:
        return ""
    placeholders = ", ".join(f":document_id_{index}" for index, _ in enumerate(document_id_filter))
    return f"AND c.document_id IN ({placeholders})"


def _document_filter_params(document_id_filter: list[UUID] | None) -> dict[str, UUID]:
    if not document_id_filter:
        return {}
    return {
        f"document_id_{index}": document_id
        for index, document_id in enumerate(document_id_filter)
    }


def _vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in embedding) + "]"
