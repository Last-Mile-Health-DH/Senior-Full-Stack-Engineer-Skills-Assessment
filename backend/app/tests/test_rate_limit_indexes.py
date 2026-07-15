from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import DATABASE_URL

BACKEND_ROOT = Path(__file__).resolve().parents[2]


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
async def test_rate_limit_indexes_exist(migrated_session: AsyncSession) -> None:
    rows = (
        await migrated_session.execute(
            text(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE tablename = 'query_audit_log'
                  AND indexname IN (
                    'query_audit_log_session_created_idx',
                    'query_audit_log_client_ip_created_idx'
                  )
                """
            )
        )
    ).mappings().all()
    index_defs = {row["indexname"]: row["indexdef"] for row in rows}

    assert "query_audit_log_session_created_idx" in index_defs
    assert "query_audit_log_client_ip_created_idx" in index_defs
    assert "client_ip IS NOT NULL" in index_defs["query_audit_log_client_ip_created_idx"]
