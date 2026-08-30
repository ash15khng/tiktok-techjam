"""Active State and per-session domain models."""

from __future__ import annotations

from dataclasses import dataclass, field

from submission.src.catalog.normalization import tokenize


@dataclass
class ActiveState:
    """Reduced current intent after all corrections and overrides are applied."""

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
        """Return compact active evidence for the optional semantic provider."""

        parts = [
            f"category={'; '.join(self.category_phrases)}" if self.category_phrases else "",
            f"preferences={'; '.join(self.preference_phrases)}" if self.preference_phrases else "",
            f"exclusions={'; '.join(self.exclusions)}" if self.exclusions else "",
            f"declined={','.join(sorted(self.suppressed_attributes))}" if self.suppressed_attributes else "",
        ]
        return " | ".join(part for part in parts if part)


@dataclass
class SessionState:
    """All mutable state isolated to one evaluator session."""

    session_id: str
    customer_profile: dict
    active: ActiveState = field(default_factory=ActiveState)
    last_ask_attribute: str | None = None
    last_recommendations: tuple[str, ...] = ()
    recommendation_exposure: set[str] = field(default_factory=set)
    turn_count: int = 0
    last_feedback_negative: bool = False
    clarification_outcomes: dict[str, str] = field(default_factory=dict)

    def answerability_posterior(self, prior: float, *, strength: float) -> float:
        """Return the catalog prior updated by this session's replies.

        Input ``prior`` and ``strength`` are in ``[0, 1]`` and positive pseudo-
        observation units respectively. The output is an answerability control
        score; it is reset naturally because every session owns a new state.
        """

        successes = sum(outcome == "answered" for outcome in self.clarification_outcomes.values())
        failures = sum(outcome in {"declined", "redirected"} for outcome in self.clarification_outcomes.values())
        bounded_prior = min(1.0, max(0.0, float(prior)))
        bounded_strength = max(0.01, float(strength))
        return (bounded_strength * bounded_prior + successes) / (
            bounded_strength + successes + failures
        )


@dataclass(frozen=True)
class QuestionDecision:
    """One optional contract attribute plus customer-facing question text."""

    ask_attribute: str | None
    message: str | None
    question_value: float | None
    reason: str
