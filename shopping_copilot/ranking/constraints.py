from __future__ import annotations

import re
from typing import Literal

from shopping_copilot.catalog.models import ProductRecord
from shopping_copilot.dialog.models import ActiveConstraint
from shopping_copilot.understanding.models import Attribute, Relation


def evaluate_constraint(
    record: ProductRecord,
    constraint: ActiveConstraint,
) -> Literal["match", "contradiction", "unknown"]:
    """Evaluates a single active constraint against product record in a strict tri-state manner."""
    if constraint.attribute == Attribute.BUDGET:
        if record.price.kind == "unknown" or record.price.lower is None:
            return "unknown"

        budget_max: float | None = None
        budget_min: float | None = None
        if len(constraint.values) >= 2:
            try:
                budget_min = float(constraint.values[0])
                budget_max = float(constraint.values[1])
            except ValueError:
                pass
        else:
            for v in constraint.values:
                try:
                    num = float(v)
                    if constraint.relation in (Relation.LTE, Relation.LT, Relation.EQ):
                        budget_max = num
                    elif constraint.relation in (Relation.GTE, Relation.GT):
                        budget_min = num
                except ValueError:
                    pass

        if record.price.matches_budget(budget_max=budget_max, budget_min=budget_min):
            return "match"

        # Soft tolerance margin (10% over max budget)
        if budget_max is not None and record.price.lower is not None:
            if record.price.lower <= budget_max * 1.10:
                return "unknown"

        return "contradiction"

    attr_name = constraint.attribute.value
    prod_values = record.attributes.get(attr_name)
    title_lower = record.search_fields.get("title", "").lower()
    features_lower = record.search_fields.get("features", "").lower()
    details_lower = record.search_fields.get("details", "").lower()
    all_text = f"{title_lower} {features_lower} {details_lower}"

    def _matches_any_value(target_val: str, candidate_vals: frozenset[str] | set[str]) -> bool:
        v_clean = target_val.lower().strip()
        v_tokens = {t for t in re.findall(r"[\w\d]+", v_clean) if len(t) > 1}

        for cv in candidate_vals:
            cv_clean = cv.lower().strip()
            # 1. Exact or substring matching in both directions
            if v_clean == cv_clean or v_clean in cv_clean or cv_clean in v_clean:
                return True
            # 2. Token intersection matching
            cv_tokens = {t for t in re.findall(r"[\w\d]+", cv_clean) if len(t) > 1}
            if v_tokens and cv_tokens:
                # If significant token overlap (or single key token matches)
                overlap = v_tokens & cv_tokens
                if len(overlap) >= max(1, min(len(v_tokens), len(cv_tokens)) // 2):
                    return True
        return False

    if constraint.relation == Relation.NEQ:
        # Exclusion evaluation
        has_excluded = False
        if prod_values:
            has_excluded = any(_matches_any_value(v, prod_values) for v in constraint.values)
        if not has_excluded:
            # Check text fields for exclusion
            has_excluded = any(v.lower().strip() in all_text for v in constraint.values if len(v.strip()) > 2)
        return "contradiction" if has_excluded else "match"

    # Positive constraint evaluation
    if prod_values:
        if any(_matches_any_value(v, prod_values) for v in constraint.values):
            return "match"

    # Check search fields (title, features, details)
    for v in constraint.values:
        v_clean = v.lower().strip()
        v_tokens = [t for t in re.findall(r"[\w\d]+", v_clean) if len(t) > 2]
        if v_clean in all_text or (v_tokens and any(t in all_text for t in v_tokens)):
            return "match"

    # If product explicitly has values for this attribute that didn't match, it is a contradiction
    if prod_values:
        return "contradiction"

    # Missing attribute is strictly UNKNOWN; never a contradiction
    return "unknown"

