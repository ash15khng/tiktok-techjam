from __future__ import annotations

import re
from typing import Any

from shopping_copilot.catalog.models import PriceValue

PRICE_RANGE_RE = re.compile(
    r"(?:from\s+)?\$?\s*(\d+(?:[.,]\d{1,2})?)\s*(?:-|to|\.\.\.)\s*\$?\s*(\d+(?:[.,]\d{1,2})?)",
    re.IGNORECASE,
)
PRICE_FROM_RE = re.compile(
    r"(?:from|starting\s+at|at\s+least|min|\$?>)\s*\$?\s*(\d+(?:[.,]\d{1,2})?)",
    re.IGNORECASE,
)
PRICE_SINGLE_RE = re.compile(
    r"\$?\s*(\d+(?:[.,]\d{1,2})?)\s*(?:usd|\$|\+)?\b",
    re.IGNORECASE,
)


def _to_float(raw: str) -> float | None:
    """Converts a parsed numeric string to float, normalizing comma decimals."""
    if not raw:
        return None
    try:
        cleaned = raw.replace(",", ".")
        val = float(cleaned)
        return round(val, 2)
    except (ValueError, TypeError):
        return None


def parse_price(raw_price: Any) -> PriceValue:
    """Deterministically parses raw price objects into a typed PriceValue."""
    if raw_price is None:
        return PriceValue(lower=None, upper=None, kind="unknown")

    # If already a number
    if isinstance(raw_price, (int, float)):
        val = round(float(raw_price), 2)
        if val < 0.0:
            return PriceValue(lower=None, upper=None, kind="unknown")
        return PriceValue(lower=val, upper=val, kind="exact")

    if not isinstance(raw_price, str):
        return PriceValue(lower=None, upper=None, kind="unknown")

    text = raw_price.strip()
    if not text or text.lower() in {"null", "none", "n/a", "nan", "unknown", "free"}:
        return PriceValue(lower=None, upper=None, kind="unknown")

    # Check for range: "$15.00 - $35.00" or "from $10 to $20"
    range_match = PRICE_RANGE_RE.search(text)
    if range_match:
        p1 = _to_float(range_match.group(1))
        p2 = _to_float(range_match.group(2))
        if p1 is not None and p2 is not None:
            low, high = min(p1, p2), max(p1, p2)
            if low == high:
                return PriceValue(lower=low, upper=high, kind="exact")
            return PriceValue(lower=low, upper=high, kind="range")

    # Check for lower bound: "From $10.00" or "$10+"
    if "+" in text:
        single_match = PRICE_SINGLE_RE.search(text)
        if single_match:
            p = _to_float(single_match.group(1))
            if p is not None:
                return PriceValue(lower=p, upper=None, kind="lower_bound")

    from_match = PRICE_FROM_RE.search(text)
    if from_match:
        p = _to_float(from_match.group(1))
        if p is not None:
            return PriceValue(lower=p, upper=None, kind="lower_bound")

    # Check for single exact price: "$24.99"
    single_match = PRICE_SINGLE_RE.search(text)
    if single_match:
        p = _to_float(single_match.group(1))
        if p is not None:
            return PriceValue(lower=p, upper=p, kind="exact")

    return PriceValue(lower=None, upper=None, kind="unknown")

