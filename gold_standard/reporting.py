"""Gold-eval trend reporting and deviation alert detection."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from statistics import mean, pstdev
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.settings import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Deviation:
    metric_name: str
    observed: float
    baseline_mean: float
    baseline_stddev: float
    z_score: float
    reason: str


def deviation_for_series(
    metric_name: str,
    observed: float,
    baseline_values: list[float],
    abs_drop: float | None = None,
    z_threshold: float = 3.0,
    min_runs: int = 3,
) -> Deviation | None:
    """Return a deviation when absolute drop or negative z-score crosses threshold."""
    if len(baseline_values) < min_runs:
        return None
    baseline_mean = mean(baseline_values)
    baseline_stddev = pstdev(baseline_values)
    drop = baseline_mean - observed
    configured_drop = settings.gold_eval_deviation_abs_drop if abs_drop is None else abs_drop
    if drop >= configured_drop:
        z_score = 0.0 if baseline_stddev == 0 else (observed - baseline_mean) / baseline_stddev
        return Deviation(metric_name, observed, baseline_mean, baseline_stddev, z_score, "absolute_drop")
    if baseline_stddev == 0:
        return None
    z_score = (observed - baseline_mean) / baseline_stddev
    if z_score <= -abs(z_threshold):
        return Deviation(metric_name, observed, baseline_mean, baseline_stddev, z_score, "z_score")
    return None


async def write_deviation_alerts(db: AsyncSession, run: dict[str, Any]) -> list[Deviation]:
    """Compare a run against compatible prior runs and write anomaly flags."""
    baseline = await _compatible_baseline(db, run)
    deviations: list[Deviation] = []
    overall = deviation_for_series(
        "gold_eval_overall",
        float(run["overall_score"]),
        [float(row["overall_score"]) for row in baseline],
        abs_drop=settings.gold_eval_deviation_abs_drop,
        z_threshold=settings.gold_eval_deviation_zscore,
    )
    if overall is not None:
        deviations.append(overall)

    category_scores = dict(run.get("category_scores") or {})
    for category, observed in category_scores.items():
        values: list[float] = []
        for row in baseline:
            prior_scores = dict(row["category_scores"] or {})
            if category in prior_scores:
                values.append(float(prior_scores[category]))
        category_drop = 3.0 if category in {"dosing", "refusal"} else settings.gold_eval_deviation_abs_drop
        deviation = deviation_for_series(
            f"gold_eval_{category}",
            float(observed),
            values,
            abs_drop=category_drop,
            z_threshold=settings.gold_eval_deviation_zscore,
        )
        if deviation is not None:
            deviations.append(deviation)

    for deviation in deviations:
        await _insert_flag(db, deviation)
        emit_alert(deviation, run)
    return deviations


def emit_alert(deviation: Deviation, run: dict[str, Any]) -> None:
    """Transport binding point for Slack/email/PagerDuty integrations."""
    logger.warning(
        "gold_eval.deviation run_id=%s metric=%s observed=%s baseline=%s z=%s reason=%s",
        run.get("id"),
        deviation.metric_name,
        deviation.observed,
        deviation.baseline_mean,
        deviation.z_score,
        deviation.reason,
    )


async def _compatible_baseline(db: AsyncSession, run: dict[str, Any]) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            text(
                """
                SELECT overall_score, category_scores
                FROM gold_eval_run
                WHERE corpus_version = :corpus_version
                  AND rubric_version = :rubric_version
                  AND judge_model = :judge_model
                  AND judge_temperature = :judge_temperature
                  AND id <> CAST(:run_id AS uuid)
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            {
                "corpus_version": run["corpus_version"],
                "rubric_version": run["rubric_version"],
                "judge_model": run["judge_model"],
                "judge_temperature": run["judge_temperature"],
                "run_id": run["id"],
                "limit": settings.gold_eval_baseline_lookback_runs,
            },
        )
    ).mappings().all()
    return [dict(row) for row in rows]


async def _insert_flag(db: AsyncSession, deviation: Deviation) -> None:
    await db.execute(
        text(
            """
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
                'nightly',
                0,
                :observed_value,
                :baseline_mean,
                :baseline_stddev,
                :z_score,
                now(),
                now()
            )
            """
        ),
        {
            "metric_name": deviation.metric_name,
            "observed_value": Decimal(str(deviation.observed)),
            "baseline_mean": Decimal(str(deviation.baseline_mean)),
            "baseline_stddev": Decimal(str(deviation.baseline_stddev)),
            "z_score": Decimal(str(deviation.z_score)),
        },
    )
