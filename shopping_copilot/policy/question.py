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

        # 3. Calculate partition value / information gain across top-50 candidates
        best_attr: str | None = None
        best_gain: float = -1.0
        candidate_sample = candidate_evidence[:50]

        for attr_str in eligible:
            values: list[str] = []
            for ev in candidate_sample:
                record = self.catalog_index.get_product(ev.parent_asin)
                if not record:
                    continue
                if attr_str == "budget":
                    if record.price.kind != "unknown" and record.price.lower is not None:
                        # Bucket prices: <25, 25-50, 50-100, >100
                        p = record.price.lower
                        if p < 25:
                            values.append("budget_under_25")
                        elif p < 50:
                            values.append("budget_25_to_50")
                        elif p < 100:
                            values.append("budget_50_to_100")
                        else:
                            values.append("budget_over_100")
                elif attr_str == "category":
                    if record.categories:
                        values.append(record.categories[-1].lower())
                else:
                    attr_vals = record.attributes.get(attr_str)
                    if attr_vals:
                        values.extend(list(attr_vals))

            if not values:
                continue

            # Compute coverage and Gini
            coverage = len(values) / max(len(candidate_sample), 1)
            counts = Counter(values)
            total = len(values)
            gini = 1.0 - sum((cnt / total) ** 2 for cnt in counts.values())

            # Information gain = Gini * coverage
            gain = gini * min(1.0, coverage)

            if len(counts) >= 2 and gain > best_gain:
                best_gain = gain
                best_attr = attr_str

        # If gain is negligible and we have high focus or few turns, don't ask
        if best_gain < 0.10:
            best_attr = None

        if best_attr is not None:
            question_text = ATTRIBUTE_QUESTIONS.get(
                best_attr, f"Could you provide more details about your preferred {best_attr}?"
            )
            return ActionDecision(
                ask_attribute=best_attr,
                message=f"I found some initial options. {question_text}",
                recommendations=top_asins,
                reason_codes=(f"clarify_{best_attr}", f"gain_{best_gain:.3f}"),
            )

        return ActionDecision(
            ask_attribute=None,
            message="Here are the best matches for your search.",
            recommendations=top_asins,
            reason_codes=("low_information_gain",),
        )

