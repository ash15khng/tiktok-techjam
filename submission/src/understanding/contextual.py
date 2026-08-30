"""Resolve short and elliptical replies against the last clarification."""

from __future__ import annotations

import re
from dataclasses import dataclass

from submission.src.catalog.attributes import (
    AttributeValueResolver,
    EmptyAttributeResolver,
    cue_attributes,
)
from submission.src.catalog.normalization import normalize_text, tokenize
from submission.src.understanding.models import Attribute


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


def explicit_attribute_for(
    text: str,
    *,
    resolver: AttributeValueResolver | None = None,
    preferred: Attribute | None = None,
) -> Attribute | None:
    """Return only attributes explicitly evidenced by the current words."""

    cues = cue_attributes(text)
    if cues:
        return Attribute(cues[0])
    selected = resolver or EmptyAttributeResolver()
    candidates = selected.candidate_attributes(
        text,
        preferred=preferred.value if preferred is not None else None,
    )
    if candidates:
        return Attribute(candidates[0])
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
    resolver: AttributeValueResolver | None = None,
) -> ResolvedReply:
    """Prefer explicit current evidence, then bounded immediate-question context."""

    cleaned = _clean_value(value)
    normalized = normalize_text(cleaned)
    if not cleaned or normalized in BARE_AFFIRMATIONS or normalized in BARE_DECLINES:
        return ResolvedReply(None, "", "non_value")

    context = _allowed_context(last_ask_attribute)
    explicit = explicit_attribute_for(cleaned, resolver=resolver, preferred=context)
    if explicit is not None:
        source = "contextual" if explicit is context and not cue_attributes(cleaned) else "explicit"
        return ResolvedReply(explicit, cleaned, source)

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
