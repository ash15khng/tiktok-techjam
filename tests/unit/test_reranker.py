from __future__ import annotations

import unittest
from types import SimpleNamespace

from shopping_copilot.config import MVPConfig
from shopping_copilot.dialog.models import ActiveState
from shopping_copilot.ranking.reranker import LightweightReranker
from shopping_copilot.retrieval.models import CandidateEvidence


class FakeStore:
    def __init__(self) -> None:
        self.products = {
            "popular": SimpleNamespace(rating_number=10_000),
            "rare": SimpleNamespace(rating_number=2),
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


if __name__ == "__main__":
    unittest.main()
