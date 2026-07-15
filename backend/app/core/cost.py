"""Model usage cost helpers."""

from __future__ import annotations

import logging
from decimal import Decimal

from app.settings import settings

logger = logging.getLogger(__name__)


def compute_cost(model: str, input_tokens: int | None, output_tokens: int | None) -> Decimal | None:
    """Compute USD cost from configured per-million token pricing.

    Missing pricing returns ``None`` instead of ``0`` so cost dashboards do not
    silently treat unpriced usage as free.
    """
    pricing = settings.model_pricing.get(model)
    if pricing is None:
        logger.warning("cost.pricing_missing model=%s", model)
        return None
    input_cost = Decimal(str(pricing["input_per_mtok"])) * Decimal(input_tokens or 0)
    output_cost = Decimal(str(pricing["output_per_mtok"])) * Decimal(output_tokens or 0)
    return (input_cost + output_cost) / Decimal("1000000")
