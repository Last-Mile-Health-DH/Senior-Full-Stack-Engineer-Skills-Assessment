"""Postgres advisory-lock guard for multi-replica scheduled jobs."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.settings import settings

logger = logging.getLogger(__name__)

JobCoroutine = Callable[[AsyncSession], Awaitable[None]]

JOB_LOCK_OFFSETS: dict[str, int] = {
    "cache_hygiene": 0,
    "nightly_grading": 10,
    "anomaly_detection": 20,
    "config_drift_check": 30,
    "gold_eval": 40,
}


def lock_id_for_job(job_name: str) -> int:
    """Return a stable advisory-lock id for a scheduled job family."""
    return settings.scheduler_leader_lock_key + JOB_LOCK_OFFSETS[job_name]


async def run_singleton(
    db: AsyncSession,
    lock_id: int,
    job_name: str,
    job_coro: JobCoroutine,
) -> bool:
    """Run ``job_coro`` only if this process acquires the advisory lock."""
    got_lock = bool(
        (
            await db.execute(
                text("SELECT pg_try_advisory_lock(:lock_id)"),
                {"lock_id": lock_id},
            )
        ).scalar_one()
    )
    if not got_lock:
        logger.info("scheduler.skip job=%s reason=not_leader", job_name)
        return False

    try:
        await job_coro(db)
        return True
    finally:
        try:
            if not db.is_active:
                await db.rollback()
            unlocked = (
                await db.execute(
                    text("SELECT pg_advisory_unlock(:lock_id)"),
                    {"lock_id": lock_id},
                )
            ).scalar_one()
            if not unlocked:
                logger.warning("scheduler.unlock_missing job=%s lock_id=%s", job_name, lock_id)
        except SQLAlchemyError:
            logger.exception("scheduler.unlock_failed job=%s lock_id=%s", job_name, lock_id)
            raise
