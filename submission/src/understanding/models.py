"""Intent Frame and Slot Update domain models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from submission.src.contracts import SemanticSlotHypothesis


class Attribute(str, Enum):
    """Allowed structured attributes from the organizer Agent contract."""

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
    """Immutable proposal to add, replace, exclude, clear, or decline a slot."""

    attribute: Attribute
    operation: str
    value: str
    raw_span: str
    source: str = "explicit"


@dataclass(frozen=True)
class IntentFrame:
    """Immutable interpretation output for exactly one customer message."""

    raw_message: str
    dialogue_acts: tuple[str, ...] # ["inform": new info, "correct": intent override, "decline": no preference]
    slot_updates: tuple[SlotUpdate, ...] # what to update in session state
    category_phrases: tuple[str, ...]
    preference_phrases: tuple[str, ...]
    exclusions: tuple[str, ...]
    override: bool
    negative_feedback: bool
    no_preference_attribute: Attribute | None
    query_rewrites: tuple[str, ...] = ()
    subjective_needs: tuple[str, ...] = ()
    semantic_hypotheses: tuple[SemanticSlotHypothesis, ...] = ()
    prompt_tokens: int = 0
    completion_tokens: int = 0
