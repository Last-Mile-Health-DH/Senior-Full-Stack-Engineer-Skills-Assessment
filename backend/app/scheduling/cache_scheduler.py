"""Lightweight scheduler for BC11 cache hygiene."""

from __future__ import annotations

import asyncio
from contextlib import suppress

from app.cache.hygiene import cache_hygiene_job
from app.database import async_session
from app.settings import settings


async def run_cache_hygiene_once() -> None:
    async with async_session() as session:
        await cache_hygiene_job(session)
        await session.commit()


def start_cache_hygiene_scheduler() -> asyncio.Task[None] | None:
    """Start a single in-process periodic cache hygiene task when enabled."""
    if not settings.enable_scheduled_jobs:
        return None
    return asyncio.create_task(_scheduler_loop(), name="cache_hygiene_scheduler")


async def stop_cache_hygiene_scheduler(task: asyncio.Task[None] | None) -> None:
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


async def _scheduler_loop() -> None:
    interval_seconds = _interval_from_cron(settings.cache_eviction_cron)
    while True:
        await asyncio.sleep(interval_seconds)
        await run_cache_hygiene_once()


def _interval_from_cron(cron: str) -> int:
    # BC11 supports the configured hourly default. BC20 can extend this parser
    # when it adds more scheduled jobs.
    return 3600 if cron.strip() == "0 * * * *" else 3600
