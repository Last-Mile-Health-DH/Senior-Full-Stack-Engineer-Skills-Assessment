from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.retrieval.hybrid_search as retrieval_module
from app.database import DATABASE_URL
from app.models import Chunk, Document
from app.retrieval.hybrid_search import (
    hybrid_search,
    lexical_search,
    reciprocal_rank_fusion,
    vector_search,
)
from app.retrieval.models import RetrievalCandidate

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DIMENSIONS = 1536


class StaticEmbeddingClient:
    def __init__(self, vector: list[float]) -> None:
        self.vector = vector

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
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


def test_reciprocal_rank_fusion_exact_scores() -> None:
    chunk_a = UUID("00000000-0000-0000-0000-00000000000a")
    chunk_b = UUID("00000000-0000-0000-0000-00000000000b")
    chunk_c = UUID("00000000-0000-0000-0000-00000000000c")

    scores = reciprocal_rank_fusion([[chunk_a, chunk_b, chunk_c], [chunk_b, chunk_a, chunk_c]], k=60)

    assert scores[chunk_a] == pytest.approx((1 / 61) + (1 / 62))
    assert scores[chunk_b] == pytest.approx((1 / 62) + (1 / 61))
    assert scores[chunk_c] == pytest.approx((1 / 63) + (1 / 63))


@pytest.mark.asyncio
async def test_hybrid_search_tie_break_prefers_nearer_vector_distance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    far = _candidate(
        "00000000-0000-0000-0000-00000000000a",
        vector_rank=1,
        lexical_rank=None,
        vector_distance=0.60,
    )
    near = _candidate(
        "00000000-0000-0000-0000-00000000000b",
        vector_rank=2,
        lexical_rank=None,
        vector_distance=0.10,
    )

    async def fake_vector_search(*args: object, **kwargs: object) -> list[RetrievalCandidate]:
        return [far, near]

    async def fake_lexical_search(*args: object, **kwargs: object) -> list[RetrievalCandidate]:
        return [
            near.model_copy(update={"vector_rank": None, "lexical_rank": 1}),
            far.model_copy(update={"vector_rank": None, "lexical_rank": 2}),
        ]

    monkeypatch.setattr(retrieval_module, "vector_search", fake_vector_search)
    monkeypatch.setattr(retrieval_module, "lexical_search", fake_lexical_search)

    result = await hybrid_search(object(), "tie", top_k=2)  # type: ignore[arg-type]

    assert result.candidates[0].chunk_id == near.chunk_id
    assert result.candidates[0].fused_score == pytest.approx(result.candidates[1].fused_score)


@pytest.mark.asyncio
async def test_vector_search_returns_nearest_indexed_chunk(migrated_session: AsyncSession) -> None:
    document = await _insert_document(migrated_session, "vector.pdf", "a" * 64)
    expected = await _insert_chunk(
        migrated_session,
        document,
        "malaria protocol dosage guidance",
        _basis_vector(0),
        chunk_index=0,
    )
    await _insert_chunk(
        migrated_session,
        document,
        "nutrition unrelated guidance",
        _basis_vector(1),
        chunk_index=1,
    )
    await migrated_session.commit()

    candidates = await vector_search(
        migrated_session,
        "malaria dosage",
        top_k=1,
        embedding_client=StaticEmbeddingClient(_basis_vector(0)),
    )

    assert [candidate.chunk_id for candidate in candidates] == [expected.id]
    assert candidates[0].vector_rank == 1
    assert candidates[0].document_filename == "vector.pdf"


@pytest.mark.asyncio
async def test_lexical_search_surfaces_rare_term_and_excludes_non_indexed(
    migrated_session: AsyncSession,
) -> None:
    indexed = await _insert_document(migrated_session, "indexed.pdf", "b" * 64)
    failed = await _insert_document(migrated_session, "failed.pdf", "c" * 64, status="failed")
    expected = await _insert_chunk(
        migrated_session,
        indexed,
        "community protocol mentions xylophonicrareterm once",
        _basis_vector(0),
        chunk_index=0,
    )
    await _insert_chunk(
        migrated_session,
        failed,
        "xylophonicrareterm should not appear from failed documents",
        _basis_vector(0),
        chunk_index=0,
    )
    await migrated_session.commit()

    candidates = await lexical_search(migrated_session, "xylophonicrareterm", top_k=5)

    assert [candidate.chunk_id for candidate in candidates] == [expected.id]
    assert candidates[0].lexical_rank == 1
    assert candidates[0].document_status == "indexed"


@pytest.mark.asyncio
async def test_hybrid_search_fuses_vector_and_lexical_ordering(
    migrated_session: AsyncSession,
) -> None:
    document = await _insert_document(migrated_session, "hybrid.pdf", "d" * 64)
    vector_match = await _insert_chunk(
        migrated_session,
        document,
        "general malaria guidance",
        _basis_vector(0),
        chunk_index=0,
    )
    lexical_match = await _insert_chunk(
        migrated_session,
        document,
        "rareterm dosing guidance",
        _basis_vector(1),
        chunk_index=1,
    )
    await migrated_session.commit()

    result = await hybrid_search(
        migrated_session,
        "rareterm",
        top_k=2,
        embedding_client=StaticEmbeddingClient(_basis_vector(0)),
        hybrid_enabled=True,
    )

    ids = [candidate.chunk_id for candidate in result.candidates]
    assert ids == [lexical_match.id, vector_match.id]
    assert result.candidates[0].vector_rank == 2
    assert result.candidates[0].lexical_rank == 1
    assert result.candidates[1].vector_rank == 1
    assert result.candidates[1].lexical_rank is None
    assert 0 < result.top_score <= (2 / (result.rrf_k + 1))


@pytest.mark.asyncio
async def test_hybrid_search_vector_only_branch(migrated_session: AsyncSession) -> None:
    document = await _insert_document(migrated_session, "vector-only.pdf", "e" * 64)
    expected = await _insert_chunk(
        migrated_session,
        document,
        "vector only rareterm",
        _basis_vector(0),
        chunk_index=0,
    )
    await migrated_session.commit()

    result = await hybrid_search(
        migrated_session,
        "rareterm",
        top_k=1,
        embedding_client=StaticEmbeddingClient(_basis_vector(0)),
        hybrid_enabled=False,
    )

    assert result.hybrid_enabled is False
    assert [candidate.chunk_id for candidate in result.candidates] == [expected.id]
    assert result.candidates[0].lexical_rank is None
    assert result.top_score == pytest.approx(1 / (result.rrf_k + 1))


@pytest.mark.asyncio
async def test_retrieval_excludes_deleted_documents(migrated_session: AsyncSession) -> None:
    document = await _insert_document(migrated_session, "deleted.pdf", "f" * 64)
    await _insert_chunk(
        migrated_session,
        document,
        "deletedterm content",
        _basis_vector(0),
        chunk_index=0,
    )
    await migrated_session.commit()
    await migrated_session.execute(delete(Document).where(Document.id == document.id))
    await migrated_session.commit()

    candidates = await lexical_search(migrated_session, "deletedterm", top_k=5)

    assert candidates == []
    chunk_count = (await migrated_session.execute(select(Chunk))).scalars().all()
    assert chunk_count == []


@pytest.mark.asyncio
async def test_query_embedding_dimension_mismatch_fails_fast(
    migrated_session: AsyncSession,
) -> None:
    with pytest.raises(ValueError, match="Embedding dimension mismatch"):
        await vector_search(
            migrated_session,
            "bad embedding",
            embedding_client=StaticEmbeddingClient([0.1, 0.2]),
        )


@pytest.mark.asyncio
async def test_vector_search_sets_hnsw_ef_search_locally(
    migrated_session: AsyncSession,
) -> None:
    document = await _insert_document(migrated_session, "hnsw.pdf", "0" * 64)
    await _insert_chunk(
        migrated_session,
        document,
        "hnsw setting content",
        _basis_vector(0),
        chunk_index=0,
    )
    await migrated_session.commit()

    await vector_search(
        migrated_session,
        "hnsw",
        top_k=1,
        embedding_client=StaticEmbeddingClient(_basis_vector(0)),
        hnsw_ef_search=77,
    )
    current = (
        await migrated_session.execute(text("SELECT current_setting('hnsw.ef_search')"))
    ).scalar_one()
    assert current == "77"

    await migrated_session.commit()
    reset = (
        await migrated_session.execute(text("SELECT current_setting('hnsw.ef_search')"))
    ).scalar_one()
    assert reset != "77"


async def _insert_document(
    session: AsyncSession,
    filename: str,
    content_hash: str,
    status: str = "indexed",
) -> Document:
    document = Document(
        filename=filename,
        content_hash=content_hash,
        status=status,
        page_count=1,
    )
    session.add(document)
    await session.flush()
    await session.refresh(document)
    return document


async def _insert_chunk(
    session: AsyncSession,
    document: Document,
    content: str,
    embedding: list[float],
    chunk_index: int,
) -> Chunk:
    row = (
        await session.execute(
            text(
                """
                INSERT INTO chunks (
                    document_id,
                    chunk_index,
                    content,
                    content_hash,
                    section_path,
                    page_number,
                    token_count,
                    embedding,
                    embedding_model
                )
                VALUES (
                    :document_id,
                    :chunk_index,
                    :content,
                    :content_hash,
                    :section_path,
                    :page_number,
                    :token_count,
                    CAST(:embedding AS vector),
                    :embedding_model
                )
                RETURNING id
                """
            ),
            {
                "document_id": document.id,
                "chunk_index": chunk_index,
                "content": content,
                "content_hash": f"{chunk_index:064x}",
                "section_path": "TEST SECTION",
                "page_number": 1,
                "token_count": len(content.split()),
                "embedding": _vector_literal(embedding),
                "embedding_model": "text-embedding-3-small",
            },
        )
    ).mappings().one()
    chunk = (await session.execute(select(Chunk).where(Chunk.id == row["id"]))).scalar_one()
    return chunk


def _basis_vector(index: int) -> list[float]:
    values = [0.0] * DIMENSIONS
    values[index] = 1.0
    return values


def _candidate(
    chunk_id: str,
    vector_rank: int | None,
    lexical_rank: int | None,
    vector_distance: float | None,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=UUID(chunk_id),
        document_id=UUID("10000000-0000-0000-0000-000000000000"),
        document_filename="tie.pdf",
        document_status="indexed",
        document_metadata={},
        content="tie-break content",
        page_number=1,
        section_path="TEST",
        vector_rank=vector_rank,
        lexical_rank=lexical_rank,
        vector_distance=vector_distance,
    )


def _vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in embedding) + "]"
