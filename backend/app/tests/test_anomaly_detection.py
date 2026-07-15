from __future__ import annotations

from app.scheduling.anomaly import cadence_for_metric, compute_z_score, is_anomalous
from gold_standard.reporting import deviation_for_series


def test_request_and_grade_metrics_dispatch_to_correct_cadence() -> None:
    assert cadence_for_metric("latency_ms") == "hourly"
    assert cadence_for_metric("cache_hit_rate") == "hourly"
    assert cadence_for_metric("grounded_false_rate") == "nightly"
    assert cadence_for_metric("judge_score_mean") == "nightly"
    assert cadence_for_metric("gold_eval_dosing") == "nightly"


def test_z_score_skips_insufficient_and_flat_baseline() -> None:
    assert compute_z_score(10, [9, 10]) is None
    assert compute_z_score(10, [5, 5, 5]) is None


def test_z_score_detects_threshold_crossing() -> None:
    result = compute_z_score(30, [10, 11, 9, 10])

    assert result is not None
    assert is_anomalous(result, threshold=3.0)


def test_gold_deviation_abs_drop_and_baseline_reset() -> None:
    deviation = deviation_for_series("gold_eval_overall", 84.0, [91.0, 90.0, 92.0], abs_drop=5.0)
    assert deviation is not None
    assert deviation.reason == "absolute_drop"

    assert deviation_for_series("gold_eval_overall", 89.0, [91.0, 90.0], abs_drop=5.0) is None
