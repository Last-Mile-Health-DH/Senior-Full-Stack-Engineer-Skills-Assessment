"""Scheduled gold-standard evaluation job."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.settings import settings
from gold_standard.reporting import write_deviation_alerts
from gold_standard.runner import run_gold_eval


async def gold_eval_job(db: AsyncSession) -> None:
    """Run the scheduled gold eval and emit deviation alerts."""
    run = await run_gold_eval(
        db,
        trigger="scheduled",
        sample_size=settings.gold_eval_sample_size,
    )
    await write_deviation_alerts(db, run)
