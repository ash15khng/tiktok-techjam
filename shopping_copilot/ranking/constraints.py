from __future__ import annotations

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

    if not prod_values:
        # Check title or search fields for positive match before falling back to unknown
        if constraint.relation != Relation.NEQ:
            title_lower = record.search_fields.get("title", "").lower()
            if title_lower and any(v.lower() in title_lower for v in constraint.values):
                return "match"
        # Missing attribute is strictly UNKNOWN; never a contradiction
        return "unknown"

    if constraint.relation == Relation.NEQ:
        # Exclusion evaluation
        has_excluded = any(v in prod_values or any(v in pv for pv in prod_values) for v in constraint.values)
        return "contradiction" if has_excluded else "match"

    # Positive constraint evaluation
    has_match = any(v in prod_values or any(v in pv for pv in prod_values) for v in constraint.values)
    return "match" if has_match else "contradiction"

