from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agents.orchestrator import assemble_generation_payload
from app.cache.exact import lookup_exact_cache, normalize_query, query_hash, write_exact_cache
from app.cache.hygiene import cache_hygiene_job
from app.cache.semantic import lookup_semantic_cache, write_semantic_cache
from app.cache.service import GeneratedAnswer, answer_with_cache
from app.database import DATABASE_URL
from app.documents.chunking import get_embedding_model
from app.retrieval.models import RetrievalAgentResult, RetrievalCandidate
from app.settings import settings

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DIMENSIONS = 1536


class StaticEmbeddingClient:
    def __init__(self, vector: list[float]) -> None:
        self.vector = vector
        self.calls = 0

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [self.vector for _ in texts]


@pytest_asyncio.fixture()
async def migrated_session():
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    engine = create_async_engine(DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with session_factory() as session:
            yield session
    finally:
        await engine.dispose()
        command.downgrade(config, "base")


def test_query_normalization_hash_equivalence() -> None:
    assert normalize_query("  What   IS Malaria??? ") == "what is malaria"
    assert query_hash("What is malaria?") == query_hash(" what   is MALARIA!!! ")


@pytest.mark.asyncio
async def test_exact_cache_hit_skips_full_pipeline(migrated_session: AsyncSession) -> None:
    document_id = await _insert_document(migrated_session)
    await write_exact_cache(
        migrated_session,
        "What is malaria?",
        "cached answer",
        [document_id],
        eligible=True,
    )
    await migrated_session.commit()

    async def full_pipeline() -> GeneratedAnswer:
        raise AssertionError("full pipeline should not run on exact-cache hit")

    result = await answer_with_cache(
        migrated_session,
        "what is malaria",
        full_pipeline,
        embedding_client=StaticEmbeddingClient(_basis_vector(0)),
    )

    assert result.generated is False
    assert result.cache_status == "exact_hit"
    assert result.answer == "cached answer"


@pytest.mark.asyncio
async def test_semantic_hit_at_093_and_miss_at_091(migrated_session: AsyncSession) -> None:
    document_id = await _insert_document(migrated_session, content_hash="b" * 64)
    await _insert_semantic_cache(
        migrated_session,
        "near hit",
        "hit answer",
        _cosine_vector(0.93),
        [document_id],
    )
    await migrated_session.commit()

    hit = await lookup_semantic_cache(
        migrated_session,
        "query",
        embedding_client=StaticEmbeddingClient(_basis_vector(0)),
    )
    assert hit is not None
    assert hit.similarity == pytest.approx(0.93, abs=0.01)

    await migrated_session.execute(text("DELETE FROM semantic_cache"))
    await _insert_semantic_cache(
        migrated_session,
        "near miss",
        "miss answer",
        _cosine_vector(0.91),
        [document_id],
    )
    await migrated_session.commit()

    miss = await lookup_semantic_cache(
        migrated_session,
        "query",
        embedding_client=StaticEmbeddingClient(_basis_vector(0)),
    )
    assert miss is None


@pytest.mark.asyncio
async def test_semantic_hit_count_and_last_used_update(migrated_session: AsyncSession) -> None:
    document_id = await _insert_document(migrated_session, content_hash="c" * 64)
    old_time = datetime.now(UTC) - timedelta(days=1)
    cache_id = await _insert_semantic_cache(
        migrated_session,
        "old",
        "answer",
        _cosine_vector(0.95),
        [document_id],
        last_used_at=old_time,
    )
    await migrated_session.commit()

    hit = await lookup_semantic_cache(
        migrated_session,
        "query",
        embedding_client=StaticEmbeddingClient(_basis_vector(0)),
    )
    assert hit is not None
    row = (
        await migrated_session.execute(
            text("SELECT hit_count, last_used_at FROM semantic_cache WHERE id = :id"),
            {"id": cache_id},
        )
    ).mappings().one()
    assert row["hit_count"] == 2
    assert row["last_used_at"] > old_time


@pytest.mark.asyncio
async def test_exact_ttl_expiry(migrated_session: AsyncSession) -> None:
    document_id = await _insert_document(migrated_session, content_hash="d" * 64)
    await migrated_session.execute(
        text(
            """
            INSERT INTO exact_cache (query_hash, answer, source_doc_ids, expires_at)
            VALUES (:query_hash, 'expired', :source_doc_ids, now() - interval '1 second')
            """
        ),
        {"query_hash": query_hash("expired"), "source_doc_ids": [document_id]},
    )
    await cache_hygiene_job(migrated_session)
    await migrated_session.commit()

    assert await lookup_exact_cache(migrated_session, "expired") is None


@pytest.mark.asyncio
async def test_semantic_lru_eviction(migrated_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "semantic_cache_max_rows", 2)
    document_id = await _insert_document(migrated_session, content_hash="e" * 64)
    now = datetime.now(UTC)
    await _insert_semantic_cache(migrated_session, "old", "old", _cosine_vector(0.95), [document_id], now - timedelta(hours=3))
    await _insert_semantic_cache(migrated_session, "middle", "middle", _cosine_vector(0.94), [document_id], now - timedelta(hours=2))
    await _insert_semantic_cache(migrated_session, "new", "new", _cosine_vector(0.93), [document_id], now - timedelta(hours=1))
    await cache_hygiene_job(migrated_session)
    await migrated_session.commit()

    rows = (await migrated_session.execute(text("SELECT representative_query FROM semantic_cache ORDER BY last_used_at"))).scalars().all()
    assert rows == ["middle", "new"]


@pytest.mark.asyncio
async def test_document_deletion_invalidation(migrated_session: AsyncSession) -> None:
    keep_doc = await _insert_document(migrated_session, content_hash="f" * 64)
    deleted_doc = await _insert_document(migrated_session, content_hash="g" * 64)
    await write_exact_cache(migrated_session, "keep", "keep", [keep_doc], eligible=True)
    await write_exact_cache(migrated_session, "delete", "delete", [deleted_doc], eligible=True)
    await _insert_semantic_cache(migrated_session, "keep", "keep", _cosine_vector(0.95), [keep_doc])
    await _insert_semantic_cache(migrated_session, "delete", "delete", _cosine_vector(0.94), [deleted_doc])
    await migrated_session.execute(text("DELETE FROM documents WHERE id = :id"), {"id": deleted_doc})
    await cache_hygiene_job(migrated_session)
    await migrated_session.commit()

    exact_rows = (await migrated_session.execute(text("SELECT answer FROM exact_cache ORDER BY answer"))).scalars().all()
    semantic_rows = (await migrated_session.execute(text("SELECT answer FROM semantic_cache ORDER BY answer"))).scalars().all()
    assert exact_rows == ["keep"]
    assert semantic_rows == ["keep"]


@pytest.mark.asyncio
async def test_prompt_cache_control_toggle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "prompt_caching_enabled", True)
    enabled = await assemble_generation_payload("query", db=object(), retrieval_agent=_Agent())
    assert enabled.system[0]["cache_control"] == {"type": "ephemeral"}

    monkeypatch.setattr(settings, "prompt_caching_enabled", False)
    disabled = await assemble_generation_payload("query", db=object(), retrieval_agent=_Agent())
    assert "cache_control" not in disabled.system[0]


@pytest.mark.asyncio
async def test_write_eligibility_false_skips_writes(migrated_session: AsyncSession) -> None:
    document_id = await _insert_document(migrated_session, content_hash="h" * 64)
    embedder = StaticEmbeddingClient(_basis_vector(0))
    await write_exact_cache(migrated_session, "blocked", "answer", [document_id], eligible=False)
    await write_semantic_cache(
        migrated_session,
        "blocked",
        "answer",
        [document_id],
        eligible=False,
        embedding_client=embedder,
    )
    await migrated_session.commit()

    exact_count = (await migrated_session.execute(text("SELECT count(*) FROM exact_cache"))).scalar_one()
    semantic_count = (await migrated_session.execute(text("SELECT count(*) FROM semantic_cache"))).scalar_one()
    assert exact_count == 0
    assert semantic_count == 0
    assert embedder.calls == 0


async def _insert_document(session: AsyncSession, content_hash: str = "a" * 64) -> UUID:
    row = (
        await session.execute(
            text(
                """
                INSERT INTO documents (filename, content_hash, status, page_count)
                VALUES ('cache.pdf', :content_hash, 'indexed', 1)
                RETURNING id
                """
            ),
            {"content_hash": content_hash},
        )
    ).mappings().one()
    return row["id"]


async def _insert_semantic_cache(
    session: AsyncSession,
    representative_query: str,
    answer: str,
    embedding: list[float],
    source_doc_ids: list[UUID],
    last_used_at: datetime | None = None,
) -> UUID:
    row = (
        await session.execute(
            text(
                """
                INSERT INTO semantic_cache (
                    query_embedding,
                    embedding_model,
                    representative_query,
                    answer,
                    source_doc_ids,
                    last_used_at
                )
                VALUES (
                    CAST(:embedding AS vector),
                    :embedding_model,
                    :representative_query,
                    :answer,
                    :source_doc_ids,
                    :last_used_at
                )
                RETURNING id
                """
            ),
            {
                "embedding": _vector_literal(embedding),
                # Explicit, never defaulted: a row whose embedding_model is wrong makes the
                # cache compare vectors across embedding spaces, which is meaningless.
                "embedding_model": get_embedding_model(),
                "representative_query": representative_query,
                "answer": answer,
                "source_doc_ids": source_doc_ids,
                "last_used_at": last_used_at or datetime.now(UTC),
            },
        )
    ).mappings().one()
    return row["id"]


def _basis_vector(index: int) -> list[float]:
    vector = [0.0] * DIMENSIONS
    vector[index] = 1.0
    return vector


def _cosine_vector(similarity: float) -> list[float]:
    vector = [0.0] * DIMENSIONS
    vector[0] = similarity
    vector[1] = math.sqrt(1 - similarity**2)
    return vector


def _vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in embedding) + "]"


class _Agent:
    async def run(self, **kwargs: object) -> RetrievalAgentResult:
        return RetrievalAgentResult(
            chunks=[
                RetrievalCandidate(
                    chunk_id=UUID("00000000-0000-0000-0000-000000000001"),
                    document_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
                    document_filename="cache.pdf",
                    document_status="indexed",
                    content="cache context",
                    page_number=1,
                )
            ]
        )


@pytest.mark.asyncio
async def test_semantic_cache_round_trips_under_any_embedding_model(
    migrated_session: AsyncSession,
) -> None:
    """Write and lookup must agree on the model, whatever the configured provider is.

    The old test helper omitted `embedding_model` and relied on the column DEFAULT
    (`text-embedding-3-small`). That passed on an OpenAI deployment and silently returned
    nothing on any other one — which is exactly the class of bug the column exists to
    prevent, hiding inside the mechanism meant to prevent it. Migration 0016 drops that
    default so an omitted model is now a loud NOT NULL violation.
    """
    document_id = await _insert_document(migrated_session, content_hash="1" * 64)
    embedder = StaticEmbeddingClient(_basis_vector(0))

    await write_semantic_cache(
        migrated_session,
        "what is the child dose",
        "cached answer",
        [document_id],
        eligible=True,
        embedding_client=embedder,
    )
    await migrated_session.commit()

    hit = await lookup_semantic_cache(
        migrated_session, "what is the child dose", embedding_client=embedder
    )

    assert hit is not None, "a row written by write_semantic_cache must be found by lookup"
    assert hit.answer == "cached answer"

    stored = (
        await migrated_session.execute(text("SELECT embedding_model FROM semantic_cache"))
    ).scalars().one()
    assert stored == get_embedding_model()


@pytest.mark.asyncio
async def test_a_vector_from_another_embedding_model_is_never_a_hit(
    migrated_session: AsyncSession,
) -> None:
    """Cosine distance between two different embedding spaces is a meaningless number.

    Serving it as a cache hit returns a stale answer to an unrelated question, so a row
    labelled with a different model must never be considered — even at similarity 1.0.
    """
    document_id = await _insert_document(migrated_session, content_hash="2" * 64)
    await migrated_session.execute(
        text(
            """
            INSERT INTO semantic_cache (
                query_embedding, embedding_model, representative_query, answer, source_doc_ids
            )
            VALUES (
                CAST(:embedding AS vector), 'some-other-provider-model',
                'q', 'answer from another model', :docs
            )
            """
        ),
        {"embedding": _vector_literal(_basis_vector(0)), "docs": [document_id]},
    )
    await migrated_session.commit()

    hit = await lookup_semantic_cache(
        migrated_session, "q", embedding_client=StaticEmbeddingClient(_basis_vector(0))
    )

    assert hit is None, "an identical vector from a different model must not be a hit"


@pytest.mark.asyncio
async def test_omitting_the_embedding_model_now_fails_loudly(
    migrated_session: AsyncSession,
) -> None:
    """Migration 0016 removed the default, so the mistake is impossible to ship silently."""
    from sqlalchemy.exc import IntegrityError

    document_id = await _insert_document(migrated_session, content_hash="3" * 64)

    with pytest.raises(IntegrityError):
        await migrated_session.execute(
            text(
                """
                INSERT INTO semantic_cache (
                    query_embedding, representative_query, answer, source_doc_ids
                )
                VALUES (CAST(:embedding AS vector), 'q', 'a', :docs)
                """
            ),
            {"embedding": _vector_literal(_basis_vector(0)), "docs": [document_id]},
        )
    await migrated_session.rollback()
