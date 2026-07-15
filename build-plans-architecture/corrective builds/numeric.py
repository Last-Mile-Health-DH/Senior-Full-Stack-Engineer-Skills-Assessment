"""
numeric.py — deterministic clinical-number extraction and support checking.

This is the BC23 primitive, factored so the pre-send output filter, the nightly re-check, and the
gold grader all share one implementation. It targets the exact failure lexical term-overlap is blind
to: an answer that states a clinically-meaningful quantity (a dose, a threshold) that appears nowhere
in the cited source. For a dosing corpus, "5 ml" vs "15 ml" is the difference the grounding gate must see.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

# Units that make a number clinically meaningful. Bare integers (page numbers, step numbers, years)
# are intentionally ignored to avoid false positives.
_UNIT = (
    r"mg/kg|ml/kg|mg|mcg|µg|ml|mL|kg|g|IU|iu|"
    r"tablets?|tabs?|puffs?|drops?|packets?|teaspoons?|tsp|"
    r"breaths?\s+per\s+minute|/min|days?|hours?|hrs?|minutes?|min|weeks?|months?|years?|"
    r"z-?scores?|mm|°C|percent|%"
)
# number: integer, decimal, or simple fraction (1/2). Optional leading approximation words are ignored.
_NUM = r"\d+(?:\.\d+)?(?:\s*/\s*\d+)?"
_CLAIM_RE = re.compile(rf"(?P<num>{_NUM})\s*(?P<unit>{_UNIT})", re.IGNORECASE)

# Unit normalization so "ml" == "mL", "hrs" == "hours", etc.
_UNIT_CANON = {
    "ml": "ml", "mL": "ml",
    "hrs": "hours", "hr": "hours", "hours": "hours", "hour": "hours",
    "min": "minutes", "minutes": "minutes", "minute": "minutes",
    "tabs": "tablet", "tab": "tablet", "tablets": "tablet", "tablet": "tablet",
    "iu": "iu", "IU": "iu",
    "days": "days", "day": "days",
    "puffs": "puff", "puff": "puff",
    "packets": "packet", "packet": "packet",
    "z-score": "zscore", "zscores": "zscore", "z-scores": "zscore", "zscore": "zscore",
}


@dataclass(frozen=True)
class Quantity:
    value: float
    unit: str
    raw: str


def _canon_unit(unit: str) -> str:
    u = unit.strip().lower().replace("  ", " ")
    u = re.sub(r"\s+", " ", u)
    return _UNIT_CANON.get(u, u)


def _to_float(num: str) -> float | None:
    num = num.strip()
    try:
        if "/" in num:
            return float(Fraction(num.replace(" ", "")))
        return float(num)
    except (ValueError, ZeroDivisionError):
        return None


def extract_quantities(text: str) -> list[Quantity]:
    """Extract clinically-meaningful (number, unit) quantities from free text."""
    out: list[Quantity] = []
    for m in _CLAIM_RE.finditer(text or ""):
        val = _to_float(m.group("num"))
        if val is None:
            continue
        out.append(Quantity(value=val, unit=_canon_unit(m.group("unit")), raw=m.group(0)))
    return out


def _same_quantity(a: Quantity, b: Quantity, tol: float = 0.0) -> bool:
    if a.unit != b.unit:
        return False
    if tol == 0.0:
        return abs(a.value - b.value) < 1e-9
    denom = max(abs(a.value), abs(b.value), 1e-9)
    return abs(a.value - b.value) / denom <= tol


def unsupported_quantities(answer: str, source_texts: list[str], tol: float = 0.0) -> list[Quantity]:
    """
    Return clinical quantities in `answer` that appear in NO source text.
    Empty list => every clinical number in the answer is supported by a cited source.
    """
    src: list[Quantity] = []
    for s in source_texts:
        src.extend(extract_quantities(s))
    missing: list[Quantity] = []
    for q in extract_quantities(answer):
        if not any(_same_quantity(q, s, tol) for s in src):
            missing.append(q)
    return missing


def numeric_claims_supported(answer: str, source_texts: list[str], tol: float = 0.0) -> tuple[bool, list[str]]:
    """(all_supported, [raw unsupported claim strings]) — the BC23 output-filter entry point."""
    missing = unsupported_quantities(answer, source_texts, tol)
    return (len(missing) == 0, [q.raw for q in missing])
