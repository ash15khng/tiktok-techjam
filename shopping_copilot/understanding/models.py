"""Intent Frame and Slot Update domain models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Attribute(str, Enum):
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


@dataclass(frozen=True)
class SlotUpdate:
    attribute: Attribute
    operation: str
    value: str
    raw_span: str


@dataclass(frozen=True)
class IntentFrame:
    raw_message: str
    dialogue_acts: tuple[str, ...]
    slot_updates: tuple[SlotUpdate, ...]
    category_phrases: tuple[str, ...]
    preference_phrases: tuple[str, ...]
    exclusions: tuple[str, ...]
    override: bool
    negative_feedback: bool
    no_preference_attribute: Attribute | None
    query_rewrites: tuple[str, ...] = ()
    subjective_needs: tuple[str, ...] = ()
    prompt_tokens: int = 0
    completion_tokens: int = 0
