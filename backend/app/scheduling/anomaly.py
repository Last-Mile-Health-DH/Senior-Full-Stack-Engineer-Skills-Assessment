"""Anomaly detection helpers for request, grade, and gold-eval metrics."""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from statistics import mean, pstdev
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.settings import settings

logger = logging.getLogger(__name__)

Cadence = Literal["hourly", "nightly"]

REQUEST_METRICS = {
    "cost_usd",
    "latency_ms",
    "cache_hit_rate",
    "output_filter_rate",
    "agentic_expanded_rate",
}
GRADE_METRICS = {"grounded_false_rate", "judge_score_mean"}


@dataclass(frozen=True, slots=True)
class ZScoreResult:
    observed: float
    baseline_mean: float
    baseline_stddev: float
    z_score: float


def cadence_for_metric(metric_name: str) -> Cadence:
    """Return the natural cadence for a metric family."""
    if metric_name in GRADE_METRICS or metric_name.startswith("gold_eval_"):
        return "nightly"
    return "hourly"


def compute_z_score(
    observed: float,
    baseline_values: Iterable[float],
    min_samples: int = 3,
) -> ZScoreResult | None:
    """Return z-score data, or ``None`` for insufficient/flat baselines."""
    values = [float(value) for value in baseline_values if math.isfinite(float(value))]
    if len(values) < min_samples:
        return None
    baseline_mean = mean(values)
    baseline_stddev = pstdev(values)
    if baseline_stddev == 0:
        return None
    return ZScoreResult(
        observed=float(observed),
        baseline_mean=baseline_mean,
        baseline_stddev=baseline_stddev,
        z_score=(float(observed) - baseline_mean) / baseline_stddev,
    )


def is_anomalous(result: ZScoreResult, threshold: float | None = None) -> bool:
    """Return whether the absolute z-score crosses the configured threshold."""
    return abs(result.z_score) >= (threshold or settings.anomaly_detection_zscore_threshold)


async def anomaly_detection_job(db: AsyncSession) -> None:
    """Compute supported anomaly flags for the latest hourly/nightly windows."""
    await _request_metric_flags(db)
    await _grade_metric_flags(db)


async def insert_anomaly_flag(
    db: AsyncSession,
    metric_name: str,
    cadence: Cadence,
    result: ZScoreResult,
    window_start_sql: str,
    window_end_sql: str,
    hour_of_day: int = 0,
) -> None:
    """Persist a threshold-crossing anomaly flag."""
    await db.execute(
        text(
            f"""
            INSERT INTO anomaly_flag (
                metric_name,
                cadence,
                hour_of_day,
                observed_value,
                baseline_mean,
                baseline_stddev,
                z_score,
                window_start,
                window_end
            )
            VALUES (
                :metric_name,
                :cadence,
                :hour_of_day,
                :observed_value,
                :baseline_mean,
                :baseline_stddev,
                :z_score,
                {window_start_sql},
                {window_end_sql}
            )
            """
        ),
        {
            "metric_name": metric_name,
            "cadence": cadence,
            "hour_of_day": hour_of_day,
            "observed_value": Decimal(str(result.observed)),
            "baseline_mean": Decimal(str(result.baseline_mean)),
            "baseline_stddev": Decimal(str(result.baseline_stddev)),
            "z_score": Decimal(str(result.z_score)),
        },
    )


async def _request_metric_flags(db: AsyncSession) -> None:
    hour_row = (
        await db.execute(
            text(
                """
                SELECT EXTRACT(HOUR FROM now() - interval '1 hour')::int AS hour_of_day
                """
            )
        )
    ).mappings().one()
    hour_of_day = int(hour_row["hour_of_day"])
    rows = (
        await db.execute(
            text(
                """
                SELECT
                    coalesce(avg(cost_usd), 0)::float AS cost_usd,
                    coalesce(avg(latency_ms), 0)::float AS latency_ms,
                    coalesce(avg(CASE WHEN cache_status IN ('exact_hit', 'semantic_hit') THEN 1 ELSE 0 END), 0)::float AS cache_hit_rate,
                    coalesce(avg(CASE WHEN output_filter_status = 'filtered' THEN 1 ELSE 0 END), 0)::float AS output_filter_rate,
                    coalesce(avg(CASE WHEN retrieval_mode = 'agentic_expanded' THEN 1 ELSE 0 END), 0)::float AS agentic_expanded_rate
                FROM query_audit_log
                WHERE created_at >= date_trunc('hour', now() - interval '1 hour')
                  AND created_at < date_trunc('hour', now())
                """
            )
        )
    ).mappings().one()
    for metric in REQUEST_METRICS:
        baseline = await _request_baseline(db, metric, hour_of_day)
        result = compute_z_score(float(rows[metric]), baseline)
        if result is not None and is_anomalous(result):
            await insert_anomaly_flag(
                db,
                metric,
                "hourly",
                result,
                "date_trunc('hour', now() - interval '1 hour')",
                "date_trunc('hour', now())",
                hour_of_day=hour_of_day,
            )


async def _grade_metric_flags(db: AsyncSession) -> None:
    rows = (
        await db.execute(
            text(
                """
                SELECT
                    coalesce(avg(CASE WHEN grounding_check_passed = false THEN 1 ELSE 0 END), 0)::float AS grounded_false_rate,
                    coalesce(avg(judge_score), 0)::float AS judge_score_mean
                FROM response_grade
                WHERE graded_at >= date_trunc('day', now() - interval '1 day')
                  AND graded_at < date_trunc('day', now())
                """
            )
        )
    ).mappings().one()
    dow = int(
        (
            await db.execute(text("SELECT EXTRACT(DOW FROM now() - interval '1 day')::int"))
        ).scalar_one()
    )
    for metric in GRADE_METRICS:
        baseline = await _grade_baseline(db, metric, dow)
        result = compute_z_score(float(rows[metric]), baseline)
        if result is not None and is_anomalous(result):
            await insert_anomaly_flag(
                db,
                metric,
                "nightly",
                result,
                "date_trunc('day', now() - interval '1 day')",
                "date_trunc('day', now())",
                hour_of_day=dow,
            )


async def _request_baseline(db: AsyncSession, metric: str, hour_of_day: int) -> list[float]:
    expression = {
        "cost_usd": "coalesce(avg(cost_usd), 0)",
        "latency_ms": "coalesce(avg(latency_ms), 0)",
        "cache_hit_rate": "coalesce(avg(CASE WHEN cache_status IN ('exact_hit', 'semantic_hit') THEN 1 ELSE 0 END), 0)",
        "output_filter_rate": "coalesce(avg(CASE WHEN output_filter_status = 'filtered' THEN 1 ELSE 0 END), 0)",
        "agentic_expanded_rate": "coalesce(avg(CASE WHEN retrieval_mode = 'agentic_expanded' THEN 1 ELSE 0 END), 0)",
    }[metric]
    rows = (
        await db.execute(
            text(
                f"""
                SELECT ({expression})::float AS value
                FROM query_audit_log
                WHERE created_at >= now() - (:days * interval '1 day')
                  AND EXTRACT(HOUR FROM created_at)::int = :hour_of_day
                GROUP BY date_trunc('day', created_at)
                """
            ),
            {"days": settings.anomaly_detection_baseline_lookback_days, "hour_of_day": hour_of_day},
        )
    ).mappings().all()
    return [float(row["value"]) for row in rows]


async def _grade_baseline(db: AsyncSession, metric: str, day_of_week: int) -> list[float]:
    expression = {
        "grounded_false_rate": "coalesce(avg(CASE WHEN grounding_check_passed = false THEN 1 ELSE 0 END), 0)",
        "judge_score_mean": "coalesce(avg(judge_score), 0)",
    }[metric]
    rows = (
        await db.execute(
            text(
                f"""
                SELECT ({expression})::float AS value
                FROM response_grade
                WHERE graded_at >= now() - (:days * interval '1 day')
                  AND EXTRACT(DOW FROM graded_at)::int = :day_of_week
                GROUP BY date_trunc('day', graded_at)
                """
            ),
            {"days": settings.anomaly_detection_baseline_lookback_days, "day_of_week": day_of_week},
        )
    ).mappings().all()
    return [float(row["value"]) for row in rows]
