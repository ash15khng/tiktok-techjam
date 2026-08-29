"""Data models and enums for message understanding and slot representations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class Attribute(str, Enum):
    """Allowed attribute categories aligned with challenge specification and evaluation."""

    CATEGORY = "category"
    MATERIAL = "material"
    COLOR = "color"
    SIZE = "size"
    STYLE = "style"
    BRAND = "brand"
    BUDGET = "budget"
    FEATURE = "feature"
    USE_CASE = "use_case"
    OTHER = "other"


class Relation(str, Enum):
    """Relational operations on slot values."""

    EQ = "eq"
    NEQ = "neq"
    LT = "lt"
    LTE = "lte"
    GT = "gt"
    GTE = "gte"
    RANGE = "range"
    CONTAINS = "contains"


@dataclass(frozen=True)
class SlotUpdate:
    """Represents a single parsed atomic change to an attribute slot."""

    attribute: Attribute
    operation: Literal["set", "add", "exclude", "clear", "set_any", "replace"]
    relation: Relation
    normalized_values: tuple[str, ...]
    alternative_group: str | None = None
    raw_span: str = ""
    char_span: tuple[int, int] = (0, 0)
    strength: Literal["hard", "soft"] = "hard"
    explicitness: Literal["explicit", "inferred"] = "explicit"
    confidence: float = 1.0
    provenance: Literal[
        "numeric_rule", "catalog_exact", "catalog_alias", "fuzzy", "semantic", "llm"
    ] = "catalog_exact"
    source_turn: int = 1


@dataclass(frozen=True)
class InterpretationAmbiguity:
    """Captures unresolvable or multiple competing attribute groundings."""

    raw_span: str
    candidate_attributes: tuple[Attribute, ...]
    candidate_values: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class IntentFrame:
    """The complete structured and unstructured representation of a parsed user message."""

    dialogue_acts: tuple[str, ...]
    slot_updates: tuple[SlotUpdate, ...]
    product_terms: tuple[str, ...]
    subjective_needs: tuple[str, ...] = field(default_factory=tuple)
    residual_terms: tuple[str, ...] = field(default_factory=tuple)
    ambiguities: tuple[InterpretationAmbiguity, ...] = field(default_factory=tuple)
    parse_confidence: float = 1.0

