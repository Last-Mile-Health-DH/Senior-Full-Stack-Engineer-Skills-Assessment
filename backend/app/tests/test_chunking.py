from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import DATABASE_URL
from app.documents.chunking import (
    DeterministicEmbeddingClient,
    StructuredBlock,
    chunk_structured_blocks,
    prepare_and_persist_document_chunks,
    validate_embedding_batch,
)
from app.documents.processing import get_upload_dir
from app.models import Chunk, Document

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class FakeEmbeddingClient:
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[0.02] * 1536 for _ in texts]


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


def test_chunk_size_limits_respect_configured_token_budget() -> None:
    block = StructuredBlock(
        content=" ".join(f"token{i}" for i in range(25)),
        page_number=1,
        block_type="paragraph",
    )

    chunks = chunk_structured_blocks([block], chunk_size_tokens=10, overlap_ratio=0.2)

    assert len(chunks) == 3
    assert all(chunk.token_count <= 10 for chunk in chunks)


def test_chunk_overlap_reuses_tail_tokens() -> None:
    block = StructuredBlock(
        content=" ".join(f"token{i}" for i in range(12)),
        page_number=1,
        block_type="paragraph",
    )

    chunks = chunk_structured_blocks([block], chunk_size_tokens=5, overlap_ratio=0.4)

    first_tokens = chunks[0].content.split()
    second_tokens = chunks[1].content.split()
    assert first_tokens[-2:] == second_tokens[:2]


def test_structure_aware_chunking_preserves_table_boundaries() -> None:
    blocks = [
        StructuredBlock(content="MALARIA PROTOCOL", page_number=1, block_type="heading"),
        StructuredBlock(
            content="assess fever danger signs before treatment",
            page_number=1,
            block_type="paragraph",
        ),
        StructuredBlock(
            content="| Drug | Dose |\n| --- | --- |\n| ACT | one tablet daily with food |",
            page_number=1,
            block_type="table",
        ),
    ]

    chunks = chunk_structured_blocks(blocks, chunk_size_tokens=6, overlap_ratio=0.0)

    table_chunks = [chunk for chunk in chunks if "| Drug | Dose |" in chunk.content]
    assert len(table_chunks) == 1
    assert table_chunks[0].section_path == "MALARIA PROTOCOL"
    assert table_chunks[0].content.startswith("MALARIA PROTOCOL")


@pytest.mark.asyncio
async def test_deterministic_embedding_generation_is_stable() -> None:
    client = DeterministicEmbeddingClient(dimensions=8)

    first = await client.embed_texts(["malaria dosage"])
    second = await client.embed_texts(["malaria dosage"])

    assert first == second
    assert len(first[0]) == 8


def test_embedding_dimension_validation_rejects_mismatches() -> None:
    with pytest.raises(ValueError, match="Embedding dimension mismatch"):
        validate_embedding_batch([[0.1, 0.2]], expected_count=1, expected_dim=1536)


@pytest.mark.asyncio
async def test_chunk_embedding_persistence_populates_vector_and_tsv(
    migrated_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content_hash = "a" * 64
    document = Document(
        filename="chunking.pdf",
        content_hash=content_hash,
        status="processing",
        page_count=1,
    )
    migrated_session.add(document)
    await migrated_session.commit()
    await migrated_session.refresh(document)

    upload_path = get_upload_dir() / f"{content_hash}.pdf"
    upload_path.parent.mkdir(parents=True, exist_ok=True)
    upload_path.write_bytes(b"%PDF-1.4\n")

    blocks = [
        StructuredBlock(content="DOSAGE SECTION", page_number=1, block_type="heading"),
        StructuredBlock(
            content="malaria fever protocol dosage table for community health workers",
            page_number=1,
            block_type="paragraph",
        ),
    ]
    monkeypatch.setattr("app.documents.chunking.extract_structured_blocks_from_pdf", lambda _path: blocks)

    try:
        summary = await prepare_and_persist_document_chunks(
            migrated_session,
            document,
            embedding_client=FakeEmbeddingClient(),
        )
        await migrated_session.commit()

        assert summary.chunk_count == 1
        chunk = (
            await migrated_session.execute(select(Chunk).where(Chunk.document_id == document.id))
        ).scalar_one()
        assert chunk.embedding_model == "text-embedding-3-small"
        assert chunk.section_path == "DOSAGE SECTION"

        row = (
            await migrated_session.execute(
                text(
                    """
                    SELECT embedding::text AS embedding_text, content_tsv::text AS tsv
                    FROM chunks
                    WHERE id = :chunk_id
                    """
                ),
                {"chunk_id": chunk.id},
            )
        ).mappings().one()
        assert row["embedding_text"].startswith("[")
        assert "malaria" in row["tsv"]
        assert "dosag" in row["tsv"]
    finally:
        if upload_path.exists():
            upload_path.unlink()
