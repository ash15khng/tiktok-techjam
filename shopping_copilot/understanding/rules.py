"""Deterministic regular expression and finite-state rule engine for parsing slot updates."""

from __future__ import annotations

import re
from typing import Literal

from shopping_copilot.config import UnderstandingConfig
from shopping_copilot.understanding.models import Attribute, Relation, SlotUpdate

# ---------------------------------------------------------------------------
# Compiled regex patterns
# ---------------------------------------------------------------------------

# Budget patterns
BUDGET_RANGE_RE = re.compile(
    r"\b(?:between\s+\$?(\d+(?:\.\d+)?)\s+(?:and|to|-)\s+\$?(\d+(?:\.\d+)?)"
    r"|from\s+\$?(\d+(?:\.\d+)?)\s+to\s+\$?(\d+(?:\.\d+)?)"
    r"|\$(\d+(?:\.\d+)?)\s*-\s*\$?(\d+(?:\.\d+)?))(?!\.\d)",
    re.IGNORECASE,
)

BUDGET_APPROX_RE = re.compile(
    r"\b(?:around|about|roughly|approx(?:\.|imately)?|~|budget\s+around)\s*\$?(\d+(?:\.\d+)?)(?!\.\d)",
    re.IGNORECASE,
)

BUDGET_LTE_RE = re.compile(
    r"(?:(?:\b(?:under|below|no\s+more\s+than|at\s+most|less\s+than)\b)|<=\s*|\$\s*<=\s*|<)\s*\$?(\d+(?:\.\d+)?)(?!\.\d)"
    r"|\b(?:budget\s+(?:is\s+|of\s+)?\$?(\d+(?:\.\d+)?)\s*(?:or\s+less|max))\b"
    r"|\b(?:budget|price)\s*[:=]\s*\$?(\d+(?:\.\d+)?)(?!\.\d)",
    re.IGNORECASE,
)

BUDGET_GTE_RE = re.compile(
    r"(?:(?:\b(?:over|above|at\s+least|no\s+less\s+than|more\s+than)\b)|>=\s*|\$\s*>=\s*>)\s*\$?(\d+(?:\.\d+)?)(?!\.\d)"
    r"|\b(?:budget\s+(?:is\s+|of\s+)?\$?(\d+(?:\.\d+)?)\s*(?:or\s+more|min))\b",
    re.IGNORECASE,
)

# Size patterns
ALPHA_SIZE_RE = re.compile(
    r"\b(?:size\s+)?(xxs|xs|small|medium|large|xl|xxl|2xl|3xl|4xl|plus\s+size|one\s+size)\b",
    re.IGNORECASE,
)

NUMERIC_SIZE_RE = re.compile(
    r"\b(?:size\s+)?(\d{1,2}(?:\.5)?)\s*(wide|narrow|regular|wide\s+width|narrow\s+width)?(?!\.\d)",
    re.IGNORECASE,
)

SIZE_RANGE_RE = re.compile(
    r"\b(?:size\s+)?(?:between\s+(\d{1,2}(?:\.5)?)\s+(?:and|to|-)\s+(\d{1,2}(?:\.5)?)"
    r"|(\d{1,2}(?:\.5)?)\s*-\s*(\d{1,2}(?:\.5)?))(?!\.\d)",
    re.IGNORECASE,
)

# Negation / Exclusion patterns
NEGATION_STARTS = (
    "not", "no", "never", "without", "avoid", "avoiding", "excluding",
    "anything but", "except", "aside from", "dont want", "don't want",
)
NEGATION_RE = re.compile(
    r"\b(?:not|no|without|avoid|avoiding|excluding|anything\s+but|except|don'?t\s+want)\s+([^,.;]+?)(?=(?:\s+but\b|\s+however\b|\s+instead\b|[,.;]|$))",
    re.IGNORECASE,
)

# Dialogue act cues
OVERRIDE_RE = re.compile(
    r"\b(?:actually|instead|ignore\s+(?:my\s+)?earlier|ignore\s+previous|change\s+(?:my\s+mind|to)|make\s+it|rather\s+than)\b",
    re.IGNORECASE,
)

INDIFFERENCE_RE = re.compile(
    r"\b(?:no\s+preference|don'?t\s+have\s+(?:a|any)\s+preference|don'?t\s+care|doesn'?t\s+matter|"
    r"either\s+is\s+fine|any\s+is\s+fine|use\s+your\s+judge?ment|no\s+additional\s+preference|anything\s+works)\b",
    re.IGNORECASE,
)

EXPLORATION_RE = re.compile(
    r"\b(?:still\s+exploring|just\s+browsing|looking\s+around|not\s+sure|open\s+to\s+suggestions|see\s+what(?:'s|\s+is)\s+out\s+there)\b",
    re.IGNORECASE,
)

COMMITMENT_RE = re.compile(
    r"\b(?:must\s+have|definitely\s+need|ready\s+to\s+buy|key\s+requirement|essential|crucial|strictly)\b",
    re.IGNORECASE,
)

HARD_MODALITY_RE = re.compile(
    r"\b(?:must|only|need|required|have\s+to|essential|key\s+requirement|strictly)\b",
    re.IGNORECASE,
)

SOFT_MODALITY_RE = re.compile(
    r"\b(?:prefer|ideally|would\s+like|nice\s+to\s+have|hope\s+for|favor)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Rule extraction functions
# ---------------------------------------------------------------------------

def detect_dialogue_acts(text: str) -> list[str]:
    """Detect dialogue acts such as override, indifference, exploration, commitment."""
    acts: list[str] = []
    if OVERRIDE_RE.search(text):
        acts.append("override")
    if INDIFFERENCE_RE.search(text):
        acts.append("indifference")
    if EXPLORATION_RE.search(text):
        acts.append("explore")
    if COMMITMENT_RE.search(text):
        acts.append("commit")
    if not acts:
        acts.append("inform")
    return acts


def extract_budget_slots(
    text: str,
    turn: int,
    config: UnderstandingConfig,
) -> list[SlotUpdate]:
    """Extract budget constraints with appropriate relational operator and normalized values."""
    updates: list[SlotUpdate] = []

    # 1. Budget Range
    for match in BUDGET_RANGE_RE.finditer(text):
        groups = match.groups()
        low = groups[0] or groups[2] or groups[4]
        high = groups[1] or groups[3] or groups[5]
        if low is not None and high is not None:
            val_low = str(round(float(low), 2))
            val_high = str(round(float(high), 2))
            updates.append(
                SlotUpdate(
                    attribute=Attribute.BUDGET,
                    operation="set",
                    relation=Relation.RANGE,
                    normalized_values=(val_low, val_high),
                    raw_span=match.group(0),
                    char_span=match.span(),
                    strength="hard",
                    explicitness="explicit",
                    confidence=config.confidence_numeric_rule,
                    provenance="numeric_rule",
                    source_turn=turn,
                )
            )
            return updates  # range takes priority

    # 2. Approximate budget (e.g. "budget around $50")
    for match in BUDGET_APPROX_RE.finditer(text):
        base_val = float(match.group(1))
        tol = base_val * config.budget_tolerance_ratio
        val_low = str(round(max(0.0, base_val - tol), 2))
        val_high = str(round(base_val + tol, 2))
        updates.append(
            SlotUpdate(
                attribute=Attribute.BUDGET,
                operation="set",
                relation=Relation.RANGE,
                normalized_values=(val_low, val_high),
                raw_span=match.group(0),
                char_span=match.span(),
                strength="soft",
                explicitness="explicit",
                confidence=config.confidence_numeric_rule,
                provenance="numeric_rule",
                source_turn=turn,
            )
        )
        return updates

    # 3. Budget LTE (under, <=)
    for match in BUDGET_LTE_RE.finditer(text):
        val = match.group(1) or match.group(2) or match.group(3)
        if val is not None:
            updates.append(
                SlotUpdate(
                    attribute=Attribute.BUDGET,
                    operation="set",
                    relation=Relation.LTE,
                    normalized_values=(str(round(float(val), 2)),),
                    raw_span=match.group(0),
                    char_span=match.span(),
                    strength="hard",
                    explicitness="explicit",
                    confidence=config.confidence_numeric_rule,
                    provenance="numeric_rule",
                    source_turn=turn,
                )
            )
            return updates

    # 4. Budget GTE (over, >=)
    for match in BUDGET_GTE_RE.finditer(text):
        val = match.group(1) or match.group(2)
        if val is not None:
            updates.append(
                SlotUpdate(
                    attribute=Attribute.BUDGET,
                    operation="set",
                    relation=Relation.GTE,
                    normalized_values=(str(round(float(val), 2)),),
                    raw_span=match.group(0),
                    char_span=match.span(),
                    strength="hard",
                    explicitness="explicit",
                    confidence=config.confidence_numeric_rule,
                    provenance="numeric_rule",
                    source_turn=turn,
                )
            )
            return updates

    return updates


def extract_size_slots(
    text: str,
    turn: int,
    config: UnderstandingConfig,
) -> list[SlotUpdate]:
    """Extract size constraints (ranges, alpha sizes, numeric sizes)."""
    updates: list[SlotUpdate] = []

    # Check explicit size range
    for match in SIZE_RANGE_RE.finditer(text):
        low = match.group(1) or match.group(3)
        high = match.group(2) or match.group(4)
        if low is not None and high is not None:
            updates.append(
                SlotUpdate(
                    attribute=Attribute.SIZE,
                    operation="set",
                    relation=Relation.RANGE,
                    normalized_values=(low, high),
                    raw_span=match.group(0),
                    char_span=match.span(),
                    strength="hard",
                    explicitness="explicit",
                    confidence=config.confidence_numeric_rule,
                    provenance="numeric_rule",
                    source_turn=turn,
                )
            )
            return updates

    # Check alpha sizes
    for match in ALPHA_SIZE_RE.finditer(text):
        size_str = match.group(1).lower().strip()
        # Canonicalize common abbreviations
        norm_map = {
            "small": "s",
            "medium": "m",
            "large": "l",
            "extra large": "xl",
        }
        canonical_size = norm_map.get(size_str, size_str)
        updates.append(
            SlotUpdate(
                attribute=Attribute.SIZE,
                operation="set",
                relation=Relation.EQ,
                normalized_values=(canonical_size,),
                raw_span=match.group(0),
                char_span=match.span(),
                strength="hard",
                explicitness="explicit",
                confidence=config.confidence_numeric_rule,
                provenance="numeric_rule",
                source_turn=turn,
            )
        )
        return updates

    # Check numeric sizes with explicit keyword "size"
    numeric_kw_re = re.compile(r"\bsize\s+(\d{1,2}(?:\.5)?)(?:\s*(wide|narrow))?\b", re.IGNORECASE)
    for match in numeric_kw_re.finditer(text):
        val = match.group(1)
        width = match.group(2)
        norm_vals = (f"{val} {width}".lower().strip(),) if width else (val,)
        updates.append(
            SlotUpdate(
                attribute=Attribute.SIZE,
                operation="set",
                relation=Relation.EQ,
                normalized_values=norm_vals,
                raw_span=match.group(0),
                char_span=match.span(),
                strength="hard",
                explicitness="explicit",
                confidence=config.confidence_numeric_rule,
                provenance="numeric_rule",
                source_turn=turn,
            )
        )
        return updates

    return updates


def extract_negation_spans(text: str) -> list[tuple[str, tuple[int, int]]]:
    """Find text spans under negative scope."""
    spans: list[tuple[str, tuple[int, int]]] = []
    for match in NEGATION_RE.finditer(text):
        span_text = match.group(1).strip()
        if span_text:
            spans.append((span_text, match.span(1)))
    return spans


def determine_modality_strength(text: str, default: Literal["hard", "soft"] = "hard") -> Literal["hard", "soft"]:
    """Determine whether the requirement expression carries hard or soft modality."""
    if HARD_MODALITY_RE.search(text):
        return "hard"
    if SOFT_MODALITY_RE.search(text):
        return "soft"
    return default
