"""Active State and per-session domain models."""

from __future__ import annotations

from dataclasses import dataclass, field

from shopping_copilot.catalog.normalization import tokenize


@dataclass
class ActiveState:
    category_phrases: list[str] = field(default_factory=list)
    preference_phrases: list[str] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    slot_values: dict[str, list[str]] = field(default_factory=dict)
    suppressed_attributes: set[str] = field(default_factory=set)
    asked_attributes: list[str] = field(default_factory=list)

    def category_terms(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(token for phrase in self.category_phrases for token in tokenize(phrase)))

    def preference_terms(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(token for phrase in self.preference_phrases for token in tokenize(phrase)))

    def query_terms(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*self.preference_terms(), *self.category_terms())))

    def context_snapshot(self) -> str:
        parts = [
            f"category={'; '.join(self.category_phrases)}" if self.category_phrases else "",
            f"preferences={'; '.join(self.preference_phrases)}" if self.preference_phrases else "",
            f"exclusions={'; '.join(self.exclusions)}" if self.exclusions else "",
            f"declined={','.join(sorted(self.suppressed_attributes))}" if self.suppressed_attributes else "",
        ]
        return " | ".join(part for part in parts if part)


@dataclass
class SessionState:
    session_id: str
    customer_profile: dict
    active: ActiveState = field(default_factory=ActiveState)
    last_ask_attribute: str | None = None
    last_recommendations: tuple[str, ...] = ()
    recommendation_exposure: set[str] = field(default_factory=set)
    turn_count: int = 0
    last_feedback_negative: bool = False


@dataclass(frozen=True)
class QuestionDecision:
    ask_attribute: str | None
    message: str | None
    question_value: float | None
    reason: str
