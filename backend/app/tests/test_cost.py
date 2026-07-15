from __future__ import annotations

from decimal import Decimal

from app.core import cost as cost_module
from app.core.cost import compute_cost
from app.settings import settings


def test_compute_cost_uses_model_pricing(monkeypatch) -> None:
    monkeypatch.setattr(
        settings,
        "model_pricing_json",
        '{"test-model":{"input_per_mtok":2.0,"output_per_mtok":6.0}}',
    )

    assert compute_cost("test-model", 1000, 500) == Decimal("0.005")


def test_unpriced_model_returns_none_and_warns(monkeypatch) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(cost_module.logger, "warning", lambda message, *args: warnings.append(message % args))
    monkeypatch.setattr(settings, "model_pricing_json", "{}")

    assert compute_cost("unpriced", 10, 10) is None
    assert warnings == ["cost.pricing_missing model=unpriced"]
