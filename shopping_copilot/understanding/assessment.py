"""Need assessment and control routing score computation."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

from shopping_copilot.config import NeedAssessorConfig
from shopping_copilot.dialog.models import ActiveState
from shopping_copilot.understanding.models import Attribute, IntentFrame


@dataclass(frozen=True)
class NeedAssessment:
    """Quantitative characterization of the customer's current decision state and query specificity."""

    decision_stage: Literal["exploring", "narrowing", "deciding", "unknown"]
    specificity: float
    commitment: float
    exploration: float
    unresolved_need_ratio: float
    focus_score: float
    reason_codes: tuple[str, ...] = field(default_factory=tuple)


class NeedAssessor:
    """Computes continuous specificity and routing focus score from active state and intent frame."""

    def __init__(self, config: NeedAssessorConfig | None = None) -> None:
        self.config = config or NeedAssessorConfig()

    def assess(
        self,
        active_state: ActiveState,
        intent_frame: IntentFrame,
        token_df: dict[str, int] | None = None,
    ) -> NeedAssessment:
        reason_codes: list[str] = []

        # 1. Category Specificity
        if active_state.category:
            # Estimate pool size ~1500 for generic category, 300 for leaf category
            pool_size = 800
            denom = math.log1p(self.config.catalog_total_products)
            cat_spec = max(0.0, min(1.0, 1.0 - math.log1p(pool_size) / denom))
            reason_codes.append("category_grounded")
        else:
            cat_spec = 0.0
            reason_codes.append("category_missing")

        # 2. Constraint Density
        explicit_constraints = [
            c for c in active_state.constraints if c.strength == "hard"
        ]
        constraint_density = min(len(explicit_constraints) / 3.0, 1.0)
        if len(explicit_constraints) >= 2:
            reason_codes.append("high_constraint_density")

        # 3. Numeric Specificity
        has_numeric = any(
            c.attribute in (Attribute.BUDGET, Attribute.SIZE)
            for c in active_state.constraints
        )
        numeric_spec = 1.0 if has_numeric else 0.0
        if has_numeric:
            reason_codes.append("numeric_constraint_present")

        # 4. Lexical Specificity (IDF mass)
        if intent_frame.product_terms and token_df:
            idf_sum = 0.0
            n = self.config.catalog_total_products
            for term in intent_frame.product_terms:
                df = token_df.get(term.lower(), 100)
                norm_idf = math.log((n + 1.0) / (df + 1.0)) / math.log(n + 1.0)
                idf_sum += norm_idf
            lexical_spec = idf_sum / len(intent_frame.product_terms)
        elif intent_frame.product_terms:
            lexical_spec = 0.6  # Default reasonable specificity for non-empty terms
        else:
            lexical_spec = 0.0

        # 5. Parse Certainty
        parse_certainty = intent_frame.parse_confidence

        # 6. Commitment and Exploration cues
        hard_cues = sum(1 for c in active_state.constraints if c.strength == "hard")
        if "commit" in intent_frame.dialogue_acts:
            hard_cues += 2
        commitment = min(hard_cues / 2.0, 1.0)

        explore_cues = 0
        if "explore" in intent_frame.dialogue_acts:
            explore_cues += 2
        if "indifference" in intent_frame.dialogue_acts or active_state.any_attributes:
            explore_cues += len(active_state.any_attributes)
        exploration = min(explore_cues / 2.0, 1.0)

        # 7. Unresolved Need Ratio
        all_needs_count = len(intent_frame.slot_updates) + len(intent_frame.subjective_needs)
        unresolved_ratio = (
            len(intent_frame.subjective_needs) / max(all_needs_count, 1)
            if all_needs_count > 0
            else 0.0
        )

        # Weighted Specificity
        specificity = (
            self.config.weight_category_specificity * cat_spec
            + self.config.weight_constraint_density * constraint_density
            + self.config.weight_numeric_specificity * numeric_spec
            + self.config.weight_lexical_specificity * lexical_spec
            + self.config.weight_parse_certainty * parse_certainty
        )
        specificity = max(0.0, min(1.0, specificity))

        # Focus score control formula
        z = (
            self.config.intercept_z
            + self.config.coef_specificity * specificity
            + self.config.coef_commitment * commitment
            - self.config.coef_exploration * exploration
            - self.config.coef_unresolved_need * unresolved_ratio
        )
        focus_score = 1.0 / (1.0 + math.exp(-z))

        # Decision Stage Classification
        if (
            exploration >= self.config.exploring_exploration_threshold
            and len(explicit_constraints) < 2
        ):
            decision_stage = "exploring"
        elif (
            specificity >= self.config.deciding_specificity_threshold
            and commitment >= self.config.deciding_commitment_threshold
        ):
            decision_stage = "deciding"
        elif explicit_constraints or active_state.category:
            decision_stage = "narrowing"
        else:
            decision_stage = "unknown"

        return NeedAssessment(
            decision_stage=decision_stage,
            specificity=round(specificity, 4),
            commitment=round(commitment, 4),
            exploration=round(exploration, 4),
            unresolved_need_ratio=round(unresolved_ratio, 4),
            focus_score=round(focus_score, 4),
            reason_codes=tuple(reason_codes),
        )

