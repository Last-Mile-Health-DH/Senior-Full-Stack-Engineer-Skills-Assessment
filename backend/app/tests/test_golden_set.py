from __future__ import annotations

import pytest


@pytest.mark.golden_set
def test_golden_set_report_buckets_retrieval_modes() -> None:
    rows = [
        {"retrieval_mode": "deterministic", "hit": True, "grounded": True, "cache_status": "miss"},
        {"retrieval_mode": "deterministic", "hit": False, "grounded": True, "cache_status": "exact_hit"},
        {"retrieval_mode": "agentic_expanded", "hit": True, "grounded": False, "cache_status": "miss"},
    ]

    report = _bucket_report(rows)

    assert report["deterministic"]["hit_rate"] == 0.5
    assert report["agentic_expanded"]["grounded_rate"] == 0.0
    assert "5-10 questions cannot recalibrate production thresholds" in report["caveat"]


def _bucket_report(rows: list[dict]) -> dict:
    buckets: dict[str, list[dict]] = {}
    for row in rows:
        buckets.setdefault(str(row["retrieval_mode"]), []).append(row)
    report = {}
    for mode, values in buckets.items():
        report[mode] = {
            "hit_rate": sum(1 for value in values if value["hit"]) / len(values),
            "grounded_rate": sum(1 for value in values if value["grounded"]) / len(values),
            "cache_statuses": sorted({value["cache_status"] for value in values}),
        }
    report["caveat"] = "5-10 questions cannot recalibrate production thresholds"
    return report
