from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Mapping, Sequence

from shopping_copilot.dialog.models import ActiveState
from shopping_copilot.indexing.store import CatalogIndex
from shopping_copilot.policy.models import ActionDecision
from shopping_copilot.retrieval.models import CandidateEvidence
from shopping_copilot.understanding.models import Attribute

ALLOWED_ATTRIBUTES = frozenset([
    "category", "material", "color", "size", "style", "brand",
    "budget", "feature", "use_case", "other",
])

ATTRIBUTE_QUESTIONS: dict[str, str] = {
    "category": "What type of product or item category are you looking for?",
    "material": "Do you have a specific material or fabric preference (such as cotton, leather, wool)?",
    "color": "What color or shade would you prefer?",
    "size": "What size or fit are you looking for?",
    "style": "Is there a particular style or design you have in mind?",
    "brand": "Do you have any preferred brand in mind?",
    "budget": "What is your target budget or price range for this item?",
    "feature": "Are there any specific features or details you require?",
    "use_case": "What occasion or intended use is this for?",
    "other": "Are there any other specifications or preferences you'd like to include?",
}


class QuestionPolicy:
    """Adaptive clarification policy computing posterior-weighted partition values across candidate pools."""

    def __init__(self, catalog_index: CatalogIndex) -> None:
        self.catalog_index = catalog_index

    def decide_action(
        self,
        active_state: ActiveState,
        candidate_evidence: Sequence[CandidateEvidence],
        turn: int,
        focus_score: float,
        asked_attributes_in_session: set[str],
        top_k: int = 10,
    ) -> ActionDecision:
        top_asins = tuple(ev.parent_asin for ev in candidate_evidence[:top_k])

        # Turn 10 is the final turn: always recommend and never ask
        if turn >= 10 or not candidate_evidence:
            return ActionDecision(
                ask_attribute=None,
                message="Here are the best matches for your requirements.",
                recommendations=top_asins,
                reason_codes=("turn_limit_reached" if turn >= 10 else "no_candidates",),
            )

        # 1. Identify active or suppressed attributes
        active_attrs = {c.attribute.value for c in active_state.constraints}
        any_attrs = {a.value for a in active_state.any_attributes}
        excluded_attrs = {exc.attribute.value for exc in active_state.exclusions}

        # 2. Filter eligible candidate attributes
        eligible: list[str] = []
        for attr_str in ALLOWED_ATTRIBUTES:
            if attr_str in any_attrs:
                continue
            if attr_str in active_attrs:
                continue
            if attr_str in asked_attributes_in_session:
                continue
            if attr_str == "category" and active_state.category:
                continue
            if attr_str == "budget" and any(c.attribute == Attribute.BUDGET for c in active_state.constraints):
                continue
            eligible.append(attr_str)

        if not eligible:
            return ActionDecision(
                ask_attribute=None,
                message="Here are the closest recommendations based on your preferences.",
                recommendations=top_asins,
                reason_codes=("no_eligible_attributes",),
            )

        # 3. Select next attribute to clarify based on shopping domain priority
        best_attr: str | None = None
        priority_order = (
            "material", "color", "feature", "style", "use_case", "size", "budget", "other",
        )
        for attr_cand in priority_order:
            if attr_cand in eligible:
                best_attr = attr_cand
                break

        if best_attr is not None:
            question_text = ATTRIBUTE_QUESTIONS.get(
                best_attr, f"Could you provide more details about your preferred {best_attr}?"
            )
            return ActionDecision(
                ask_attribute=best_attr,
                message=f"I found some initial options. {question_text}",
                recommendations=top_asins,
                reason_codes=(f"clarify_{best_attr}",),
            )

        return ActionDecision(
            ask_attribute=None,
            message="Here are the best matches for your search.",
            recommendations=top_asins,
            reason_codes=("low_information_gain",),
        )

