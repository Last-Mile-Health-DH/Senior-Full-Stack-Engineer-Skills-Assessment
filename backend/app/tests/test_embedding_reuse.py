"""Embedding reuse: identical chunk text is embedded once, ever.

Document-level dedup (SHA-256 of the file bytes) already stops the same *file* being
ingested twice. It cannot help when the same content arrives as different bytes — a
re-export, a re-scan, the same protocol bundled inside a larger document, the same
boilerplate appendix in three different guidelines. Those are byte-different files whose
chunks are textually identical, and each of those chunks would otherwise be embedded and
paid for again.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.documents.chunking import PreparedChunk, _embed_with_reuse, get_embedding_model
from app.database import DATABASE_URL

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DIMENSIONS = 1536


class CountingEmbeddingClient:
    """Counts exactly how many texts were sent to the provider."""

    def __init__(self) -> None:
        self.embedded: list[str] = []

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.embedded.extend(texts)
        return [[float(len(text))] + [0.0] * (DIMENSIONS - 1) for text in texts]


@pytest_asyncio.fixture()
async def session():
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    engine = create_async_engine(DATABASE_URL, echo=False)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as db:
            yield db
    finally:
        await engine.dispose()
        command.downgrade(config, "base")


def _chunk(index: int, content: str) -> PreparedChunk:
    import hashlib

    return PreparedChunk(
        chunk_index=index,
        content=content,
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        section_path=None,
        page_number=1,
        token_count=len(content.split()),
    )


async def _insert_document(db: AsyncSession) -> str:
    row = (
        await db.execute(
            text(
                """
                INSERT INTO documents (filename, content_hash, status, page_count)
                VALUES ('a.pdf', :hash, 'indexed', 1) RETURNING id
                """
            ),
            {"hash": uuid4().hex + uuid4().hex},
        )
    ).mappings().one()
    await db.commit()
    return row["id"]


async def _store(db: AsyncSession, document_id, chunks, vectors) -> None:
    for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
        await db.execute(
            text(
                """
                INSERT INTO chunks (
                    document_id, chunk_index, content, content_hash,
                    page_number, embedding, embedding_model
                )
                VALUES (
                    :document_id, :index, :content, :hash, 1,
                    CAST(:embedding AS vector), :model
                )
                """
            ),
            {
                "document_id": document_id,
                "index": index,
                "content": chunk.content,
                "hash": chunk.content_hash,
                "page_number": 1,
                "embedding": "[" + ",".join(f"{v:.8f}" for v in vector) + "]",
                "model": get_embedding_model(),
            },
        )
    await db.commit()


@pytest.mark.asyncio
async def test_first_ingestion_embeds_everything(session: AsyncSession) -> None:
    client = CountingEmbeddingClient()
    chunks = [_chunk(0, "child dose is 5 ml"), _chunk(1, "adult dose is 10 ml")]

    vectors = await _embed_with_reuse(session, chunks, client)

    assert len(client.embedded) == 2
    assert len(vectors) == 2


@pytest.mark.asyncio
async def test_identical_content_in_a_different_document_is_not_re_embedded(
    session: AsyncSession,
) -> None:
    """The same protocol re-exported as a different file must not be paid for twice."""
    document_id = await _insert_document(session)
    first = CountingEmbeddingClient()
    chunks = [_chunk(0, "child dose is 5 ml"), _chunk(1, "adult dose is 10 ml")]
    vectors = await _embed_with_reuse(session, chunks, first)
    await _store(session, document_id, chunks, vectors)

    # A byte-different file whose chunks are textually identical.
    second = CountingEmbeddingClient()
    reused = await _embed_with_reuse(session, [_chunk(0, "child dose is 5 ml")], second)

    assert second.embedded == [], "identical text must never be embedded twice"
    assert reused[0] == pytest.approx(vectors[0]), "the reused vector must be the same vector"


@pytest.mark.asyncio
async def test_reupload_by_a_different_session_does_not_re_embed_the_source(
    session: AsyncSession,
) -> None:
    """The dedup scope is the whole vector store, not a user or a chat session.

    A document already indexed by one user is re-uploaded by a *different* user in a *different*
    chat session (a distinct document id, distinct file bytes, same content). Because embedding
    reuse is keyed on the chunk content hash and the embedding model — with no session or user in
    the key — the second upload embeds nothing and pays nothing: the source is deduplicated in the
    vector database rather than indexed a second time.
    """
    # User A, session 1: first ingestion of the source.
    doc_user_a = await _insert_document(session)
    user_a = CountingEmbeddingClient()
    source = [_chunk(0, "give ORS 10 ml/kg after each loose stool"), _chunk(1, "zinc for 14 days")]
    vectors = await _embed_with_reuse(session, source, user_a)
    await _store(session, doc_user_a, source, vectors)
    assert len(user_a.embedded) == 2, "the first ingestion embeds the source once"

    # User B, session 2: a separate document row (different id/bytes), identical content.
    doc_user_b = await _insert_document(session)
    assert doc_user_b != doc_user_a
    user_b = CountingEmbeddingClient()
    reused = await _embed_with_reuse(session, [_chunk(0, "give ORS 10 ml/kg after each loose stool"),
                                              _chunk(1, "zinc for 14 days")], user_b)

    assert user_b.embedded == [], "a re-upload in another session must not re-embed the source"
    assert len(reused) == len(vectors)
    for got, want in zip(reused, vectors, strict=True):
        assert got == pytest.approx(want), "it reuses the exact vectors already in the store"


@pytest.mark.asyncio
async def test_only_the_new_chunks_of_an_overlapping_document_are_embedded(
    session: AsyncSession,
) -> None:
    """A guideline that re-uses a boilerplate appendix pays only for what is new."""
    document_id = await _insert_document(session)
    first = CountingEmbeddingClient()
    shared = [_chunk(0, "shared appendix text")]
    vectors = await _embed_with_reuse(session, shared, first)
    await _store(session, document_id, shared, vectors)

    second = CountingEmbeddingClient()
    mixed = [_chunk(0, "shared appendix text"), _chunk(1, "brand new clinical guidance")]
    await _embed_with_reuse(session, mixed, second)

    assert second.embedded == ["brand new clinical guidance"]


@pytest.mark.asyncio
async def test_a_vector_from_a_different_model_is_never_reused(
    session: AsyncSession, monkeypatch
) -> None:
    """Reusing a vector across embedding models would compare incomparable spaces."""
    document_id = await _insert_document(session)
    chunks = [_chunk(0, "child dose is 5 ml")]
    vectors = await _embed_with_reuse(session, chunks, CountingEmbeddingClient())
    await _store(session, document_id, chunks, vectors)

    monkeypatch.setenv("EMBEDDING_MODEL", "some-other-model")
    client = CountingEmbeddingClient()
    await _embed_with_reuse(session, chunks, client)

    assert client.embedded == ["child dose is 5 ml"]


@pytest.mark.asyncio
async def test_a_chunk_repeated_within_one_document_is_embedded_once(
    session: AsyncSession,
) -> None:
    client = CountingEmbeddingClient()
    repeated = [_chunk(0, "same line"), _chunk(1, "same line"), _chunk(2, "different")]

    vectors = await _embed_with_reuse(session, repeated, client)

    assert sorted(client.embedded) == ["different", "same line"]
    assert len(vectors) == 3
    assert vectors[0] == vectors[1]
