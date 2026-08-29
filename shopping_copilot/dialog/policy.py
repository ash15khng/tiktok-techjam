"""Metric-aware clarification selection."""

from __future__ import annotations

import re
from collections import Counter

from shopping_copilot.catalog.store import CatalogStore
from shopping_copilot.config import MVPConfig
from shopping_copilot.dialog.models import QuestionDecision, SessionState
from shopping_copilot.retrieval.models import CandidateEvidence, RetrievalAssessment


MATERIAL_RE = re.compile(r"\b(cotton|polyester|nylon|leather|wool|spandex|silk|rayon)\b", re.I)
COLOR_RE = re.compile(r"\b(black|white|blue|red|pink|green|brown|gray|grey|purple|yellow|orange|navy)\b", re.I)
SIZE_RE = re.compile(r"\b(?:size\s*)?(xs|s|m|l|xl|xxl|wide|narrow|small|medium|large)\b", re.I)

QUESTION_TEXT = {
    "feature": "Which feature matters most for the product you want?",
    "material": "Do you have a material preference?",
    "color": "Do you have a color preference?",
    "style": "What style or fit do you prefer?",
    "size": "What size or fit requirement should I use?",
    "use_case": "What occasion or use case is this for?",
    "budget": "What budget range should I use?",
    "brand": "Do you have a brand preference?",
    "category": "Which product category should I focus on?",
    "other": "What other requirement matters most for the item you want?",
}

# Released-data answerability audit, rounded and deliberately conservative.
# These priors are not probabilities of the hidden target and need more tuning.
ANSWERABILITY_PRIOR = {
    "feature": 0.95,
    "material": 0.72,
    "color": 0.28,
    "style": 0.38,
    "size": 0.25,
    "use_case": 0.35,
    "budget": 0.22,
    "brand": 0.15,
    "category": 0.40,
}


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
            value = coverage * diversity * ANSWERABILITY_PRIOR[attribute] * (1.0 - confidence)
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
        product = self.store.get(parent_asin)
        text = product.search_text
        if attribute == "feature":
            return product.features[0][:80].casefold() if product.features else None
        if attribute == "material":
            match = MATERIAL_RE.search(text)
            return match.group(1).casefold() if match else None
        if attribute == "color":
            match = COLOR_RE.search(text)
            return match.group(1).casefold() if match else None
        if attribute == "size":
            match = SIZE_RE.search(text)
            return match.group(1).casefold() if match else None
        if attribute == "style":
            return next((value.casefold()[:80] for value in product.details if "style" in value.casefold() or "fit" in value.casefold()), None)
        if attribute == "use_case":
            return next((word for word in ("hiking", "running", "gym", "winter", "outdoor", "work", "wedding", "travel") if word in text.casefold()), None)
        if attribute == "budget":
            return str(int(product.price // 25) * 25) if product.price is not None else None
        if attribute == "brand":
            return product.store.casefold() if product.store else None
        if attribute == "category":
            return product.categories[-1].casefold() if product.categories else None
        return None
