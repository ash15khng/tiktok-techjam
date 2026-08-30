"""Metric-aware clarification selection."""

from __future__ import annotations

from collections import Counter

from submission.src.catalog.attributes import QUESTION_TEXT
from submission.src.catalog.store import CatalogStore
from submission.src.config import AgentConfig
from submission.src.dialog.models import QuestionDecision, SessionState
from submission.src.retrieval.models import CandidateEvidence, RetrievalAssessment


QUESTION_ATTRIBUTE_ORDER = (
    "feature",
    "material",
    "color",
    "style",
    "size",
    "use_case",
    "budget",
    "brand",
    "category",
)
NEUTRAL_ANSWERABILITY_PRIOR = 0.50


class QuestionPolicy:
    """Choose at most one target-blind, score-aware clarification."""

    def __init__(self, store: CatalogStore, config: AgentConfig) -> None:
        self.store = store
        self.config = config

    def choose(
        self,
        state: SessionState,
        candidates: list[CandidateEvidence],
        assessment: RetrievalAssessment,
        turn: int,
    ) -> QuestionDecision:
        """Return a structured question decision for the current ranked list."""

        if turn >= self.config.max_turns:
            return QuestionDecision(None, None, None, "last_turn")
        active = state.active
        unavailable = active.suppressed_attributes | set(active.asked_attributes)
        top = candidates[: self.config.question_candidate_depth]
        stability_weight = min(1.0, max(0.0, self.config.question_stability_weight))
        preference_confidence = min(
            1.0,
            len(active.preference_phrases)
            / max(0.01, self.config.question_preference_saturation),
        )
        confidence = min(
            1.0,
            stability_weight * assessment.top10_stability
            + (1.0 - stability_weight) * preference_confidence,
        )

        # A declined or unanswerable structured question is a signal to let the
        # customer name their own priority. This avoids serially interrogating
        # them about every catalog field and gives one broad recovery turn.
        previous_question_unanswered = (
            state.last_ask_attribute is not None
            and state.last_ask_attribute != "other"
            and state.last_ask_attribute in active.suppressed_attributes
        )
        if previous_question_unanswered and "other" not in unavailable:
            value = max(0.0, self.config.unanswered_recovery_weight * (1.0 - confidence))
            return QuestionDecision(
                "other",
                QUESTION_TEXT["other"],
                value,
                "unanswered_question_recovery",
            )

        values: list[tuple[float, str]] = []
        for attribute in QUESTION_ATTRIBUTE_ORDER:
            if attribute in unavailable:
                continue
            groups = [self._value(attribute, item.parent_asin) for item in top]
            grounded = [value for value in groups if value]
            coverage = len(grounded) / max(1, len(top))
            counts = Counter(grounded)
            diversity = (
                1.0
                - sum((count / len(grounded)) ** 2 for count in counts.values())
                if grounded
                else 0.0
            )
            prior = self._baseline_answerability(attribute)
            answerability = state.answerability_posterior(
                prior,
                strength=self.config.question_prior_strength,
            )
            value = coverage * diversity * answerability * (1.0 - confidence)
            values.append((value, attribute))

        if values:
            best_value, best_attribute = max(
                values,
                key=lambda pair: (pair[0], -QUESTION_ATTRIBUTE_ORDER.index(pair[1])),
            )
            if best_value >= self.config.question_value_threshold or state.last_feedback_negative:
                return QuestionDecision(
                    best_attribute,
                    QUESTION_TEXT[best_attribute],
                    best_value,
                    "candidate_partition",
                )
        if (
            "other" not in unavailable
            and confidence < self.config.broad_recovery_confidence_ceiling
        ):
            value = max(0.0, self.config.broad_recovery_weight * (1.0 - confidence))
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
            return NEUTRAL_ANSWERABILITY_PRIOR
        return attributes.baseline_answerability(attribute)
