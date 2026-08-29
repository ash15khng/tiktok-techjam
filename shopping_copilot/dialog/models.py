"""Data models for dialogue context, active session state, and customer profiles."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from shopping_copilot.understanding.models import Attribute, IntentFrame, Relation


@dataclass(frozen=True)
class CustomerProfile:
    """Anonymized prior customer behavior and preference profile."""

    summary: str = ""
    preference_tags: tuple[str, ...] = field(default_factory=tuple)
    average_prior_rating: float | None = None
    purchase_frequency: str | None = None
    rating_style: str | None = None

    @classmethod
    def from_dict(cls, data: dict | None) -> CustomerProfile:
        if not data:
            return cls()
        tags = data.get("preference_tags") or []
        return cls(
            summary=str(data.get("summary") or ""),
            preference_tags=tuple(str(t) for t in tags),
            average_prior_rating=(
                float(data["average_prior_rating"])
                if data.get("average_prior_rating") is not None
                else None
            ),
            purchase_frequency=(
                str(data["purchase_frequency"])
                if data.get("purchase_frequency") is not None
                else None
            ),
            rating_style=(
                str(data["rating_style"])
                if data.get("rating_style") is not None
                else None
            ),
        )


@dataclass(frozen=True)
class ActiveConstraint:
    """A currently active positive or negative constraint on a product attribute."""

    attribute: Attribute
    relation: Relation
    values: tuple[str, ...]
    alternative_group: str | None = None
    strength: Literal["hard", "soft"] = "hard"
    confidence: float = 1.0
    source_turn: int = 1
    raw_span: str = ""


@dataclass(frozen=True)
class ActiveState:
    """Immutable state containing all currently active constraints, exclusions, and context."""

    category: str | None = None
    constraints: tuple[ActiveConstraint, ...] = field(default_factory=tuple)
    exclusions: tuple[ActiveConstraint, ...] = field(default_factory=tuple)
    any_attributes: frozenset[Attribute] = field(default_factory=frozenset)
    profile_preferences: tuple[str, ...] = field(default_factory=tuple)
    raw_phrases: tuple[str, ...] = field(default_factory=tuple)
    residual_product_terms: tuple[str, ...] = field(default_factory=tuple)
    turn: int = 0

    def get_constraints(self, attribute: Attribute) -> tuple[ActiveConstraint, ...]:
        """Return all active positive constraints for a specific attribute."""
        return tuple(c for c in self.constraints if c.attribute == attribute)

    def get_exclusions(self, attribute: Attribute) -> tuple[ActiveConstraint, ...]:
        """Return all active exclusions for a specific attribute."""
        return tuple(c for c in self.exclusions if c.attribute == attribute)

    def is_suppressed(self, attribute: Attribute) -> bool:
        """Check if an attribute is marked as ANY (indifference / no preference)."""
        return attribute in self.any_attributes


@dataclass(frozen=True)
class TurnRecord:
    """Auditable log of a single conversation turn."""

    turn: int
    user_message: str
    intent_frame: IntentFrame
    recommendations: tuple[str, ...] = field(default_factory=tuple)
    ask_attribute: Attribute | None = None
    question_text: str | None = None


@dataclass(frozen=True)
class DialogueContext:
    """Input context passed to the message interpreter."""

    active_state: ActiveState
    last_ask_attribute: Attribute | None = None
    last_recommendations: tuple[str, ...] = field(default_factory=tuple)
    turn: int = 1


@dataclass(frozen=True)
class SessionState:
    """Top-level session container holding user profile and state history."""

    session_id: str
    user_profile: CustomerProfile
    active_state: ActiveState = field(default_factory=ActiveState)
    turn_history: tuple[TurnRecord, ...] = field(default_factory=tuple)
    last_ask_attribute: Attribute | None = None
    last_recommendations: tuple[str, ...] = field(default_factory=tuple)

