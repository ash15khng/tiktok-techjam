from __future__ import annotations

from collections import defaultdict
from typing import Sequence

from shopping_copilot.indexing.store import CatalogIndex
from shopping_copilot.retrieval.models import RetrievalRequest
from shopping_copilot.understanding.models import Attribute, Relation


class AttributeCandidateGenerator:
    """Inverted index candidate generator matching structured categories and attributes."""

    NAME = "attribute_posting"

    def __init__(self, catalog_index: CatalogIndex) -> None:
        self.catalog_index = catalog_index

    def generate(self, request: RetrievalRequest, limit: int = 150) -> list[tuple[str, float]]:
        candidate_pool: set[str] = set()

        # 1. Gather category posting set
        cat_matches: frozenset[str] = frozenset()
        if request.category:
            cat_matches = self.catalog_index.filter_by_category(request.category)
            candidate_pool.update(cat_matches)

        # 2. Gather positive constraint posting sets
        attr_postings: dict[str, set[str]] = defaultdict(set)
        for c in request.active_constraints:
            if c.attribute == Attribute.BUDGET:
                # Parse numeric budget if available
                budget_max: float | None = None
                budget_min: float | None = None
                for v in c.values:
                    try:
                        num = float(v)
                        if c.relation in (Relation.LTE, Relation.LT, Relation.EQ):
                            budget_max = num
                        elif c.relation in (Relation.GTE, Relation.GT):
                            budget_min = num
                    except ValueError:
                        pass
                price_set = self.catalog_index.filter_by_price(min_price=budget_min, max_price=budget_max)
                attr_postings[f"budget_{c.relation.value}"].update(price_set)
                candidate_pool.update(price_set)
            else:
                for val in c.values:
                    matched_set = self.catalog_index.filter_by_attribute(c.attribute, val)
                    attr_postings[f"{c.attribute.value}_{val}"].update(matched_set)
                    candidate_pool.update(matched_set)

        # 3. Handle exclusions
        excluded_asins: set[str] = set()
        for exc in request.exclusions:
            for val in exc.values:
                excluded = self.catalog_index.filter_by_attribute(exc.attribute, val)
                excluded_asins.update(excluded)

        candidate_pool.difference_update(excluded_asins)

        if not candidate_pool:
            return []

        # 4. Score candidates
        scored_candidates: list[tuple[str, float]] = []
        for asin in candidate_pool:
            record = self.catalog_index.get_product(asin)
            if not record:
                continue

            hard_matches = 0
            soft_matches = 0
            hard_contradictions = 0
            soft_contradictions = 0

            # Check category match
            cat_match = 1.0 if (cat_matches and asin in cat_matches) else 0.0

            # Check each active constraint
            for c in request.active_constraints:
                attr_name = c.attribute.value
                prod_values = record.attributes.get(attr_name, frozenset())

                if c.attribute == Attribute.BUDGET:
                    # Budget evaluation
                    budget_max = None
                    budget_min = None
                    for v in c.values:
                        try:
                            num = float(v)
                            if c.relation in (Relation.LTE, Relation.LT, Relation.EQ):
                                budget_max = num
                            elif c.relation in (Relation.GTE, Relation.GT):
                                budget_min = num
                        except ValueError:
                            pass
                    if not record.price.matches_budget(budget_max=budget_max, budget_min=budget_min):
                        if c.strength == "hard":
                            hard_contradictions += 1
                        else:
                            soft_contradictions += 1
                    elif record.price.kind != "unknown":
                        if c.strength == "hard":
                            hard_matches += 1
                        else:
                            soft_matches += 1
                else:
                    if not prod_values:
                        # Unknown attribute: contributes 0 (never a contradiction)
                        continue

                    # Check if any requested value matches product attributes
                    has_match = any(v in prod_values or any(v in pv for pv in prod_values) for v in c.values)
                    if has_match:
                        if c.strength == "hard":
                            hard_matches += 1
                        else:
                            soft_matches += 1
                    else:
                        # Product has known values but none match
                        if c.strength == "hard":
                            hard_contradictions += 1
                        else:
                            soft_contradictions += 1

            score = (
                2.5 * hard_matches
                + 1.0 * soft_matches
                + 0.4 * cat_match
                - 6.0 * hard_contradictions
                - 1.0 * soft_contradictions
            )
            scored_candidates.append((asin, round(score, 4)))

        # Sort descending by score, tie-break by ASIN
        scored_candidates.sort(key=lambda item: (-item[1], item[0]))
        return scored_candidates[:limit]
