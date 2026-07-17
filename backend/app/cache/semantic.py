"""Semantic response cache backed by pgvector cosine similarity."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.exact import CacheHit
from app.documents.chunking import (
    EmbeddingClient,
    get_embedding_client,
    get_embedding_dim,
    validate_embedding_batch,
)
from app.settings import settings


async def embed_cache_query(
    query: str,
    embedding_client: EmbeddingClient | None = None,
) -> list[float]:
    client = embedding_client or get_embedding_client()
    embeddings = await client.embed_texts([query])
    validate_embedding_batch(embeddings, expected_count=1, expected_dim=get_embedding_dim())
    return embeddings[0]


async def lookup_semantic_cache(
    db: AsyncSession,
    query: str,
    embedding_client: EmbeddingClient | None = None,
) -> CacheHit | None:
    if not settings.semantic_cache_enabled:
        return None
    embedding = await embed_cache_query(query, embedding_client)
    row = (
        await db.execute(
            text(
                """
                SELECT id, answer, source_doc_ids, 1 - (query_embedding <=> CAST(:embedding AS vector)) AS similarity
                FROM semantic_cache
                ORDER BY query_embedding <=> CAST(:embedding AS vector)
                LIMIT 1
                """
            ),
            {"embedding": _vector_literal(embedding)},
        )
    ).mappings().first()
    if row is None:
        return None
    similarity = float(row["similarity"])
    if similarity < settings.semantic_cache_threshold:
        return None
    await db.execute(
        text(
            """
            UPDATE semantic_cache
            SET hit_count = hit_count + 1,
                last_used_at = now()
            WHERE id = :id
            """
        ),
        {"id": row["id"]},
    )
    return CacheHit(
        answer=str(row["answer"]),
        source_doc_ids=list(row["source_doc_ids"] or []),
        cache_status="semantic_hit",
        similarity=similarity,
    )


async def write_semantic_cache(
    db: AsyncSession,
    query: str,
    answer: str,
    source_doc_ids: list[UUID],
    eligible: bool,
    embedding_client: EmbeddingClient | None = None,
) -> None:
    """Write a semantic-cache row if the answer is cache-eligible."""
    # TODO(BC14): eligible = output_filter_status == "passed"
    if not eligible or not settings.semantic_cache_enabled:
        return
    embedding = await embed_cache_query(query, embedding_client)
    await db.execute(
        text(
            """
            INSERT INTO semantic_cache (
                query_embedding,
                representative_query,
                answer,
                source_doc_ids,
                hit_count,
                last_used_at
            )
            VALUES (
                CAST(:embedding AS vector),
                :representative_query,
                :answer,
                :source_doc_ids,
                1,
                now()
            )
            """
        ),
        {
            "embedding": _vector_literal(embedding),
            "representative_query": query,
            "answer": answer,
            "source_doc_ids": source_doc_ids,
        },
    )


def _vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in embedding) + "]"
