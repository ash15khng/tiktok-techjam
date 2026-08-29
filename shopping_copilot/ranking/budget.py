"""Conservative numeric budget interpretation for catalog prices."""

from __future__ import annotations

import re
from dataclasses import dataclass


NUMBER = r"\$?\s*(\d+(?:\.\d{1,2})?)"
BETWEEN_RE = re.compile(rf"\b(?:between|from)\s+{NUMBER}\s+(?:and|to|-)\s+{NUMBER}", re.I)
UPPER_RE = re.compile(rf"\b(?:under|below|up\s+to|at\s+most|no\s+more\s+than)\s+{NUMBER}", re.I)
LOWER_RE = re.compile(rf"\b(?:over|above|at\s+least|no\s+less\s+than)\s+{NUMBER}", re.I)
AROUND_RE = re.compile(rf"\b(?:budget\s+)?(?:around|about|roughly|approximately)\s+{NUMBER}", re.I)


@dataclass(frozen=True)
class BudgetRange:
    lower: float | None
    upper: float | None
    approximate: bool = False


def parse_budget(value: str) -> BudgetRange | None:
    between = BETWEEN_RE.search(value)
    if between:
        first, second = sorted((float(between.group(1)), float(between.group(2))))
        return BudgetRange(first, second)
    upper = UPPER_RE.search(value)
    if upper:
        return BudgetRange(None, float(upper.group(1)))
    lower = LOWER_RE.search(value)
    if lower:
        return BudgetRange(float(lower.group(1)), None)
    around = AROUND_RE.search(value)
    if around:
        center = float(around.group(1))
        tolerance = max(10.0, center * 0.25)
        return BudgetRange(max(0.0, center - tolerance), center + tolerance, True)
    return None


def price_signal(price: float | None, values: list[str]) -> float:
    """Return match/violation/unknown as +1/-1/0; missing price stays neutral."""

    if price is None:
        return 0.0
    parsed = next((budget for value in reversed(values) if (budget := parse_budget(value))), None)
    if parsed is None:
        return 0.0
    if parsed.lower is not None and price < parsed.lower:
        return -0.5 if parsed.approximate else -1.0
    if parsed.upper is not None and price > parsed.upper:
        return -0.5 if parsed.approximate else -1.0
    return 1.0
