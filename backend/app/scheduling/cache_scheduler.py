"""Lightweight in-process scheduler for cache, grading, anomaly, and gold jobs."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from app.cache.hygiene import cache_hygiene_job
from app.database import async_session
from app.scheduling.anomaly import anomaly_detection_job
from app.scheduling.grading import config_drift_check_job, nightly_grading_job
from app.scheduling.singleton import lock_id_for_job, run_singleton
from app.settings import settings

logger = logging.getLogger(__name__)

SessionJob = Callable[..., Awaitable[None]]


async def run_cache_hygiene_once() -> None:
    await _run_singleton_once("cache_hygiene", cache_hygiene_job)


async def run_nightly_grading_once() -> None:
    await _run_singleton_once("nightly_grading", nightly_grading_job)


async def run_anomaly_detection_once() -> None:
    await _run_singleton_once("anomaly_detection", anomaly_detection_job)


async def run_config_drift_check_once() -> None:
    await _run_singleton_once("config_drift_check", config_drift_check_job)


async def run_gold_eval_once() -> None:
    try:
        from gold_standard.scheduler_job import gold_eval_job
    except Exception as exc:  # pragma: no cover - only happens if package import is broken.
        logger.warning("gold_eval.import_failed error=%s", exc)
        return
    await _run_singleton_once("gold_eval", gold_eval_job)


def start_schedulers() -> list[asyncio.Task[None]]:
    """Start configured in-process scheduled-job loops."""
    if not settings.enable_scheduled_jobs:
        return []
    return [
        asyncio.create_task(_scheduler_loop("cache_hygiene", run_cache_hygiene_once, settings.cache_eviction_cron), name="cache_hygiene_scheduler"),
        asyncio.create_task(_scheduler_loop("nightly_grading", run_nightly_grading_once, settings.grading_job_cron), name="nightly_grading_scheduler"),
        asyncio.create_task(_scheduler_loop("anomaly_detection", run_anomaly_detection_once, settings.grading_job_cron), name="anomaly_detection_scheduler"),
        asyncio.create_task(_scheduler_loop("config_drift_check", run_config_drift_check_once, settings.grading_job_cron), name="config_drift_scheduler"),
        asyncio.create_task(_scheduler_loop("gold_eval", run_gold_eval_once, settings.gold_eval_cron), name="gold_eval_scheduler"),
    ]


async def stop_schedulers(tasks: list[asyncio.Task[None]]) -> None:
    for task in tasks:
        task.cancel()
    for task in tasks:
        with suppress(asyncio.CancelledError):
            await task


async def _scheduler_loop(job_name: str, job: Callable[[], Awaitable[None]], cron: str) -> None:
    while True:
        await asyncio.sleep(_seconds_until_next_run(cron))
        try:
            await job()
        except Exception:
            logger.exception("scheduler.job_failed job=%s", job_name)


async def _run_singleton_once(job_name: str, job: SessionJob) -> None:
    async with async_session() as session:
        await run_singleton(session, lock_id_for_job(job_name), job_name, job)
        await session.commit()


def _interval_from_cron(cron: str) -> int:
    # Minimal parser for this assessment's fixed hourly/nightly cron defaults.
    parts = cron.split()
    if len(parts) != 5:
        return 3600
    minute, hour, *_ = parts
    if hour == "*":
        return 3600
    return 24 * 3600


def _seconds_until_next_run(cron: str, now: datetime | None = None) -> int:
    """Return delay until the next fixed hourly/daily cron tick.

    This intentionally supports the repo's documented simple cron forms:
    ``M * * * *`` and ``M H * * *``. Unsupported expressions fall back to the
    legacy fixed interval rather than failing startup.
    """
    current = now or datetime.now(UTC)
    parts = cron.split()
    if len(parts) != 5:
        return _interval_from_cron(cron)
    minute_s, hour_s, *_ = parts
    try:
        minute = int(minute_s)
    except ValueError:
        return _interval_from_cron(cron)
    if not 0 <= minute <= 59:
        return _interval_from_cron(cron)

    if hour_s == "*":
        target = current.replace(minute=minute, second=0, microsecond=0)
        if target <= current:
            target += timedelta(hours=1)
        return max(1, int((target - current).total_seconds()))

    try:
        hour = int(hour_s)
    except ValueError:
        return _interval_from_cron(cron)
    if not 0 <= hour <= 23:
        return _interval_from_cron(cron)

    target = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= current:
        target += timedelta(days=1)
    return max(1, int((target - current).total_seconds()))


# Backward-compatible names used by earlier tests/imports.
def start_cache_hygiene_scheduler() -> asyncio.Task[None] | None:
    if not settings.enable_scheduled_jobs:
        return None
    return asyncio.create_task(
        _scheduler_loop("cache_hygiene", run_cache_hygiene_once, settings.cache_eviction_cron),
        name="cache_hygiene_scheduler",
    )


async def stop_cache_hygiene_scheduler(task: asyncio.Task[None] | None) -> None:
    await stop_schedulers([task] if task is not None else [])
