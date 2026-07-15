from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.cache.semantic import lookup_semantic_cache, write_semantic_cache
from app.database import DATABASE_URL
from app.scheduling.grading import config_drift_check_job
from app.settings import settings

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DIMENSIONS = 1536


class StaticEmbeddingClient:
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0] + [0.0] * (DIMENSIONS - 1) for _ in texts]


@pytest_asyncio.fixture()
async def migrated_session():
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    engine = create_async_engine(DATABASE_URL, echo=False)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()
        command.downgrade(config, "base")


@pytest.mark.asyncio
async def test_semantic_cache_lookup_scoped_by_embedding_model(
    migrated_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = await _insert_document(migrated_session)
    monkeypatch.setenv("EMBEDDING_MODEL", "model-a")
    await write_semantic_cache(
        migrated_session,
        "dose",
        "cached answer",
        [document_id],
        eligible=True,
        embedding_client=StaticEmbeddingClient(),
    )
    await migrated_session.commit()

    hit = await lookup_semantic_cache(migrated_session, "dose", StaticEmbeddingClient())
    assert hit is not None

    monkeypatch.setenv("EMBEDDING_MODEL", "model-b")
    miss = await lookup_semantic_cache(migrated_session, "dose", StaticEmbeddingClient())
    assert miss is None


@pytest.mark.asyncio
async def test_config_drift_deletes_stale_semantic_cache_rows(
    migrated_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = await _insert_document(migrated_session)
    monkeypatch.setenv("EMBEDDING_MODEL", "stale-model")
    await write_semantic_cache(
        migrated_session,
        "dose",
        "stale",
        [document_id],
        eligible=True,
        embedding_client=StaticEmbeddingClient(),
    )
    await migrated_session.commit()

    monkeypatch.setattr(settings, "embedding_model", "current-model")
    await config_drift_check_job(migrated_session)
    await migrated_session.commit()

    count = (await migrated_session.execute(text("SELECT count(*) FROM semantic_cache"))).scalar_one()
    assert count == 0


async def _insert_document(session: AsyncSession) -> UUID:
    row = (
        await session.execute(
            text(
                """
                INSERT INTO documents (filename, content_hash, status, page_count)
                VALUES ('cache.pdf', :hash, 'indexed', 1)
                RETURNING id
                """
            ),
            {"hash": "f" * 64},
        )
    ).mappings().one()
    return row["id"]
