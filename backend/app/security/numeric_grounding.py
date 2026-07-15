"""Deterministic numeric grounding checks shared by filters and grading."""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

_UNIT = (
    r"mg/kg|ml/kg|mg|mcg|ug|µg|ml|mL|kg|g|grams?|IU|iu|"
    r"tablets?|tabs?|puffs?|drops?|packets?|teaspoons?|tsp|"
    r"breaths?\s+per\s+minute|/min|days?|hours?|hrs?|minutes?|min|weeks?|months?|years?|"
    r"z-?scores?|mm|c|°C|percent|%"
)
_NUM = r"\d+(?:\.\d+)?(?:\s*/\s*\d+)?"
_CLAIM_RE = re.compile(rf"(?P<num>{_NUM})\s*(?P<unit>{_UNIT})", re.IGNORECASE)
_UNIT_CANON = {
    "ml": "ml",
    "ml/kg": "ml/kg",
    "hrs": "hours",
    "hr": "hours",
    "hour": "hours",
    "hours": "hours",
    "min": "minutes",
    "minute": "minutes",
    "minutes": "minutes",
    "tab": "tablet",
    "tabs": "tablet",
    "tablet": "tablet",
    "tablets": "tablet",
    "iu": "iu",
    "day": "days",
    "days": "days",
    "puff": "puff",
    "puffs": "puff",
    "packet": "packet",
    "packets": "packet",
    "gram": "g",
    "grams": "g",
    "ug": "mcg",
    "µg": "mcg",
    "z-score": "zscore",
    "z-scores": "zscore",
    "zscores": "zscore",
}


@dataclass(frozen=True)
class Quantity:
    value: float
    unit: str
    raw: str


def extract_quantities(text: str) -> list[Quantity]:
    quantities: list[Quantity] = []
    for match in _CLAIM_RE.finditer(text or ""):
        value = _to_float(match.group("num"))
        if value is None:
            continue
        quantities.append(
            Quantity(
                value=value,
                unit=_canon_unit(match.group("unit")),
                raw=match.group(0),
            )
        )
    return quantities


def numeric_claims_supported(
    answer: str,
    source_texts: list[str],
    tol: float = 0.0,
) -> tuple[bool, list[str]]:
    source_quantities: list[Quantity] = []
    for source in source_texts:
        source_quantities.extend(extract_quantities(source))

    unsupported: list[str] = []
    for answer_quantity in extract_quantities(answer):
        if not any(_same_quantity(answer_quantity, source_quantity, tol) for source_quantity in source_quantities):
            unsupported.append(answer_quantity.raw)
    return not unsupported, unsupported


def _canon_unit(unit: str) -> str:
    normalized = re.sub(r"\s+", " ", unit.strip().lower())
    return _UNIT_CANON.get(normalized, normalized)


def _to_float(value: str) -> float | None:
    try:
        if "/" in value:
            return float(Fraction(value.replace(" ", "")))
        return float(value)
    except (ValueError, ZeroDivisionError):
        return None


def _same_quantity(left: Quantity, right: Quantity, tol: float) -> bool:
    if left.unit != right.unit:
        return False
    if tol == 0.0:
        return abs(left.value - right.value) < 1e-9
    denom = max(abs(left.value), abs(right.value), 1e-9)
    return abs(left.value - right.value) / denom <= tol
