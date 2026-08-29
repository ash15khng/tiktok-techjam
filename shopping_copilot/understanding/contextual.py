"""Resolve short and elliptical replies against the last clarification."""

from __future__ import annotations

import re
from dataclasses import dataclass

from shopping_copilot.catalog.normalization import normalize_text, tokenize
from shopping_copilot.understanding.models import Attribute


MATERIALS = frozenset(("cotton", "polyester", "nylon", "leather", "wool", "spandex", "silk", "rayon", "fabric"))
COLORS = frozenset(("black", "white", "blue", "red", "pink", "green", "brown", "gray", "grey", "purple", "yellow", "orange", "navy"))
USE_CASES = frozenset(("hiking", "running", "gym", "winter", "outdoor", "work", "wedding", "travel", "sports"))
SIZE_TERMS = frozenset(("size", "sizing", "width", "wide", "narrow", "small", "medium", "large", "xs", "xl", "xxl"))
STYLE_TERMS = frozenset(("style", "fit", "sleeve", "neck", "closure", "department", "platform", "heel", "heels", "stiletto", "wedge", "slim", "loose"))
FEATURE_TERMS = frozenset(("feature", "waterproof", "breathable", "cushion", "cushioned", "support", "supportive", "non-slip", "nonslip", "pocket", "pockets"))
CATEGORY_TERMS = frozenset(("shoe", "shoes", "boot", "boots", "shirt", "shirts", "dress", "dresses", "pants", "jewelry", "watch", "watches", "bag", "bags"))
BARE_DECLINES = frozenset(("no", "nope", "none", "any", "anything", "either", "whatever", "doesn't matter", "does not matter", "dont care", "don't care"))
BARE_AFFIRMATIONS = frozenset(("yes", "yeah", "yep", "sure", "okay", "ok"))
SHORT_REPLY_MAX_TOKENS = 8
SHORT_REPLY_MAX_CHARS = 100


@dataclass(frozen=True)
class ResolvedReply:
    attribute: Attribute | None
    value: str
    source: str


def _allowed_context(attribute: str | None) -> Attribute | None:
    if not attribute:
        return None
    try:
        parsed = Attribute(attribute)
    except ValueError:
        return None
    return parsed if parsed is not Attribute.OTHER else None


def _clean_value(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" -;,.\t\r\n/\\")


def explicit_attribute_for(text: str) -> Attribute | None:
    """Return only attributes explicitly evidenced by the current words."""

    terms = set(tokenize(text, drop_stopwords=False))
    lowered = normalize_text(text)
    if (
        "budget" in terms
        or "$" in text
        or re.search(r"\b(?:under|below|over|above|around|between|up\s+to|at\s+(?:most|least))\s+\$?\d", lowered)
    ):
        return Attribute.BUDGET
    if terms & MATERIALS:
        return Attribute.MATERIAL
    if terms & COLORS or "color" in terms or "colour" in terms:
        return Attribute.COLOR
    if terms & USE_CASES:
        return Attribute.USE_CASE
    if terms & SIZE_TERMS or re.search(r"\bsize\s*\d+(?:\.5)?\b", lowered):
        return Attribute.SIZE
    if terms & STYLE_TERMS:
        return Attribute.STYLE
    if "brand" in terms or "manufacturer" in terms or "made by" in lowered:
        return Attribute.BRAND
    if terms & FEATURE_TERMS:
        return Attribute.FEATURE
    if "category" in terms or terms & CATEGORY_TERMS:
        return Attribute.CATEGORY
    return None


def contextual_no_preference(message: str, last_ask_attribute: str | None) -> Attribute | None:
    """Interpret a bare decline only when a specific clarification supplies context."""

    context = _allowed_context(last_ask_attribute)
    if context is None:
        return None
    return context if normalize_text(_clean_value(message)) in BARE_DECLINES else None


def resolve_reply_value(
    value: str,
    *,
    last_ask_attribute: str | None,
    override: bool,
) -> ResolvedReply:
    """Prefer explicit current evidence, then bounded immediate-question context."""

    cleaned = _clean_value(value)
    normalized = normalize_text(cleaned)
    if not cleaned or normalized in BARE_AFFIRMATIONS or normalized in BARE_DECLINES:
        return ResolvedReply(None, "", "non_value")

    explicit = explicit_attribute_for(cleaned)
    if explicit is not None:
        return ResolvedReply(explicit, cleaned, "explicit")

    context = _allowed_context(last_ask_attribute)
    terms = tokenize(cleaned, drop_stopwords=False)
    if (
        not override
        and context is not None
        and len(cleaned) <= SHORT_REPLY_MAX_CHARS
        and len(terms) <= SHORT_REPLY_MAX_TOKENS
    ):
        if context is Attribute.BUDGET and re.fullmatch(r"\$?\s*\d+(?:\.\d{1,2})?", cleaned):
            amount = cleaned.lstrip("$ ")
            cleaned = f"budget around ${amount}"
        return ResolvedReply(context, cleaned, "contextual")

    return ResolvedReply(Attribute.FEATURE, cleaned, "fallback")
