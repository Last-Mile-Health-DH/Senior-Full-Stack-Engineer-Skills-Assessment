from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import DATABASE_URL
from app.scheduling.singleton import lock_id_for_job, run_singleton

BACKEND_ROOT = Path(__file__).resolve().parents[2]


@pytest_asyncio.fixture()
async def session_factory():
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    engine = create_async_engine(DATABASE_URL, echo=False)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()
        command.downgrade(config, "base")


@pytest.mark.asyncio
async def test_only_one_concurrent_singleton_job_executes(session_factory) -> None:
    executions = 0
    lock_id = lock_id_for_job("cache_hygiene")

    async def job(_session: AsyncSession) -> None:
        nonlocal executions
        executions += 1
        await asyncio.sleep(0.2)

    async with session_factory() as first, session_factory() as second:
        results = await asyncio.gather(
            run_singleton(first, lock_id, "cache_hygiene", job),
            run_singleton(second, lock_id, "cache_hygiene", job),
        )

    assert sorted(results) == [False, True]
    assert executions == 1


@pytest.mark.asyncio
async def test_lock_releases_when_job_raises(session_factory) -> None:
    lock_id = lock_id_for_job("nightly_grading")

    async def failing(_session: AsyncSession) -> None:
        raise RuntimeError("boom")

    async def successful(_session: AsyncSession) -> None:
        return None

    async with session_factory() as first:
        with pytest.raises(RuntimeError):
            await run_singleton(first, lock_id, "nightly_grading", failing)

    async with session_factory() as second:
        assert await run_singleton(second, lock_id, "nightly_grading", successful) is True


def test_job_families_have_distinct_lock_ids() -> None:
    assert lock_id_for_job("cache_hygiene") != lock_id_for_job("nightly_grading")
    assert lock_id_for_job("nightly_grading") != lock_id_for_job("gold_eval")
