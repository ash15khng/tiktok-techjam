"""Metric-aware clarification selection."""

from __future__ import annotations

from collections import Counter

from shopping_copilot.catalog.attributes import QUESTION_TEXT
from shopping_copilot.catalog.store import CatalogStore
from shopping_copilot.config import MVPConfig
from shopping_copilot.dialog.models import QuestionDecision, SessionState
from shopping_copilot.retrieval.models import CandidateEvidence, RetrievalAssessment


class QuestionPolicy:
    """Target-blind answerability and partition heuristic.

    Constants are good-enough MVP guesses and need more scenario-level tuning.
    """

    attribute_order = ("feature", "material", "color", "style", "size", "use_case", "budget", "brand", "category")

    def __init__(self, store: CatalogStore, config: MVPConfig) -> None:
        self.store = store
        self.config = config

    def choose(
        self,
        state: SessionState,
        candidates: list[CandidateEvidence],
        assessment: RetrievalAssessment,
        turn: int,
    ) -> QuestionDecision:
        if turn >= 10:
            return QuestionDecision(None, None, None, "last_turn")
        active = state.active
        unavailable = active.suppressed_attributes | set(active.asked_attributes)
        top = candidates[:50]
        confidence = min(1.0, 0.55 * assessment.top10_stability + 0.45 * min(1.0, len(active.preference_phrases) / 3.0))

        # A declined or unanswerable structured question is a signal to let the
        # customer name their own priority. This avoids serially interrogating
        # them about every catalog field and gives one broad recovery turn.
        previous_question_unanswered = (
            state.last_ask_attribute is not None
            and state.last_ask_attribute != "other"
            and state.last_ask_attribute in active.suppressed_attributes
        )
        if previous_question_unanswered and "other" not in unavailable:
            value = max(0.0, 0.85 * (1.0 - confidence))
            return QuestionDecision("other", QUESTION_TEXT["other"], value, "unanswered_question_recovery")

        values: list[tuple[float, str]] = []
        for attribute in self.attribute_order:
            if attribute in unavailable:
                continue
            groups = [self._value(attribute, item.parent_asin) for item in top]
            grounded = [value for value in groups if value]
            coverage = len(grounded) / max(1, len(top))
            counts = Counter(grounded)
            diversity = 1.0 - sum((count / len(grounded)) ** 2 for count in counts.values()) if grounded else 0.0
            prior = self._baseline_answerability(attribute)
            answerability = state.answerability_posterior(prior)
            value = coverage * diversity * answerability * (1.0 - confidence)
            values.append((value, attribute))

        if values:
            best_value, best_attribute = max(values, key=lambda pair: (pair[0], -self.attribute_order.index(pair[1])))
            if best_value >= self.config.question_value_threshold or state.last_feedback_negative:
                return QuestionDecision(best_attribute, QUESTION_TEXT[best_attribute], best_value, "candidate_partition")
        if "other" not in unavailable and confidence < 0.92:
            value = max(0.0, 0.75 * (1.0 - confidence))
            return QuestionDecision("other", QUESTION_TEXT["other"], value, "broad_fallback")
        return QuestionDecision(None, None, None, "confidence_or_no_answerable_attribute")

    def _value(self, attribute: str, parent_asin: str) -> str | None:
        attributes = getattr(self.store, "attributes", None)
        if attributes is None:
            return None
        return attributes.representative_value(parent_asin, attribute)

    def _baseline_answerability(self, attribute: str) -> float:
        attributes = getattr(self.store, "attributes", None)
        if attributes is None:
            return 0.50
        return attributes.baseline_answerability(attribute)
