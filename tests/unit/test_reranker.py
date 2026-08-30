from __future__ import annotations

import unittest
from types import SimpleNamespace

from submission.src.config import MVPConfig
from submission.src.dialog.models import ActiveState
from submission.src.ranking.reranker import LightweightReranker
from submission.src.retrieval.models import CandidateEvidence


class FakeStore:
    def __init__(self) -> None:
        self.products = {
            "popular": SimpleNamespace(rating_number=10_000, price=80.0),
            "rare": SimpleNamespace(rating_number=2, price=50.0),
        }

    def inverse_document_frequency(self, terms):
        return {term: 1.0 for term in terms}

    def product_terms(self, parent_asin):
        return frozenset({"leather"})

    def product_token_text(self, parent_asin):
        return "leather"

    def get(self, parent_asin):
        return self.products[parent_asin]


class RerankerTest(unittest.TestCase):
    def test_capped_popularity_breaks_an_evidence_tie(self) -> None:
        reranker = LightweightReranker(FakeStore(), MVPConfig())
        active = ActiveState(preference_phrases=["leather"])
        candidates = [
            CandidateEvidence("rare", rrf_score=0.1),
            CandidateEvidence("popular", rrf_score=0.1),
        ]

        ranked = reranker.rank(candidates, active, {})

        self.assertEqual(ranked[0].parent_asin, "popular")

    def test_budget_match_changes_order_and_missing_price_is_neutral(self) -> None:
        store = FakeStore()
        store.products["matching"] = SimpleNamespace(rating_number=2, price=50.0)
        store.products["over"] = SimpleNamespace(rating_number=2, price=80.0)
        store.products["missing"] = SimpleNamespace(rating_number=2, price=None)
        reranker = LightweightReranker(store, MVPConfig())
        active = ActiveState(
            preference_phrases=["under $60"],
            slot_values={"budget": ["under $60"]},
        )
        candidates = [
            CandidateEvidence("over", rrf_score=0.1),
            CandidateEvidence("missing", rrf_score=0.1),
            CandidateEvidence("matching", rrf_score=0.1),
        ]

        ranked = reranker.rank(candidates, active, {})

        self.assertEqual([item.parent_asin for item in ranked], ["matching", "missing", "over"])


if __name__ == "__main__":
    unittest.main()
