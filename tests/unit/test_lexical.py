from __future__ import annotations

import unittest

from submission.src.catalog.models import CatalogSearchResult, ProductRecord
from submission.src.config import AgentConfig
from submission.src.dialog.models import ActiveState
from submission.src.retrieval.lexical import LexicalRetriever
from submission.src.retrieval.models import RetrievalPlan


def _product(parent_asin: str, rating_number: int) -> ProductRecord:
    return ProductRecord(
        parent_asin=parent_asin,
        title="running shoe",
        categories=("Shoes", "Fashion Sneakers"),
        features=(),
        details=(),
        store="",
        description=(),
        price=None,
        average_rating=4.0,
        rating_number=rating_number,
    )


class _Store:
    def __init__(self) -> None:
        self.products = {
            "LOW": _product("LOW", 2),
            "HIGH": _product("HIGH", 500),
        }

    def rare_terms(self, terms, limit):
        return terms[:limit]

    def search(self, terms, *, weights, limit, require_all=False):
        if not terms:
            return []
        return [
            CatalogSearchResult("LOW", -2.0),
            CatalogSearchResult("HIGH", -1.0),
        ][:limit]

    def get(self, parent_asin):
        return self.products[parent_asin]

    def structural_search(self, category_phrases, preference_phrases, *, limit):
        return [CatalogSearchResult("HIGH", -3.0)][:limit]


class LexicalRetrieverTest(unittest.TestCase):
    def test_category_popular_route_reorders_a_broad_category_pool(self) -> None:
        active = ActiveState(category_phrases=["fashion sneakers"])
        routes = LexicalRetriever(_Store(), AgentConfig()).retrieve(
            active,
            RetrievalPlan(focus_score=0.2, generator_weights={}, generator_limit=2),
        )

        self.assertEqual([item.parent_asin for item in routes["category"]], ["LOW", "HIGH"])
        self.assertEqual([item.parent_asin for item in routes["category_popular"]], ["HIGH", "LOW"])

    def test_structural_route_is_explicitly_gated(self) -> None:
        active = ActiveState(
            category_phrases=["fashion sneakers"],
            preference_phrases=["breathable"],
        )
        plan = RetrievalPlan(focus_score=0.8, generator_weights={}, generator_limit=2)

        disabled = LexicalRetriever(_Store(), AgentConfig()).retrieve(active, plan)
        enabled = LexicalRetriever(
            _Store(),
            AgentConfig(structural_retrieval_enabled=True),
        ).retrieve(active, plan)

        self.assertNotIn("structural", disabled)
        self.assertEqual(
            [item.parent_asin for item in enabled["structural"]],
            ["HIGH"],
        )


if __name__ == "__main__":
    unittest.main()
