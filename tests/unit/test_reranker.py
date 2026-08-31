from __future__ import annotations

import unittest
from types import SimpleNamespace

from submission.src.config import AgentConfig
from submission.src.dialog.models import ActiveState
from submission.src.ranking.ordering import FrozenTopKOrderer
from submission.src.ranking.reranker import LightweightReranker
from submission.src.retrieval.models import CandidateEvidence


class FakeStore:
    def __init__(self) -> None:
        self.products = {
            "popular": SimpleNamespace(rating_number=10_000, price=80.0),
            "rare": SimpleNamespace(rating_number=2, price=50.0),
            "phrase": SimpleNamespace(rating_number=2, price=50.0),
        }

    def inverse_document_frequency(self, terms):
        return {term: 1.0 for term in terms}

    def product_terms(self, parent_asin):
        if parent_asin == "phrase":
            return frozenset({"wide", "toe", "box"})
        return frozenset({"leather"})

    def product_token_text(self, parent_asin):
        if parent_asin == "phrase":
            return "shoes with a wide toe box"
        return "leather"

    def get(self, parent_asin):
        return self.products[parent_asin]


class RerankerTest(unittest.TestCase):
    def test_capped_popularity_breaks_an_evidence_tie(self) -> None:
        reranker = LightweightReranker(FakeStore(), AgentConfig())
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
        reranker = LightweightReranker(store, AgentConfig())
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

    def test_secondary_priors_cannot_change_frozen_membership(self) -> None:
        config = AgentConfig(
            max_recommendations=2,
            membership_preserving_ordering=True,
            phrase_rarity_order_weight=0.0,
        )
        orderer = FrozenTopKOrderer(FakeStore(), config)
        candidates = [
            CandidateEvidence("rare", final_score=0.9),
            CandidateEvidence("phrase", final_score=0.8),
            CandidateEvidence("popular", final_score=0.7),
        ]

        ordered = orderer.order(candidates, ActiveState(), {})

        self.assertEqual(
            {item.parent_asin for item in ordered[:2]},
            {"rare", "phrase"},
        )
        self.assertEqual(ordered[2].parent_asin, "popular")

    def test_pool_local_phrase_rarity_can_reorder_frozen_members(self) -> None:
        config = AgentConfig(
            max_recommendations=2,
            membership_preserving_ordering=True,
            phrase_rarity_order_weight=0.15,
            ordering_popularity_weight=0.0,
            ordering_profile_weight=0.0,
        )
        orderer = FrozenTopKOrderer(FakeStore(), config)
        active = ActiveState(preference_phrases=["wide toe box"])
        candidates = [
            CandidateEvidence("rare", final_score=0.9),
            CandidateEvidence("phrase", final_score=0.8),
        ]

        ordered = orderer.order(candidates, active, {})

        self.assertEqual(ordered[0].parent_asin, "phrase")
        self.assertGreater(
            ordered[0].raw_scores["ordering_phrase_bonus"],
            0.0,
        )

    def test_popularity_ordering_can_be_disabled_for_corrected_intent(self) -> None:
        config = AgentConfig(
            max_recommendations=2,
            membership_preserving_ordering=True,
            phrase_rarity_order_weight=0.0,
            ordering_popularity_weight=0.18,
            ordering_profile_weight=0.0,
        )
        orderer = FrozenTopKOrderer(FakeStore(), config)
        candidates = [
            CandidateEvidence("rare", final_score=0.9),
            CandidateEvidence("popular", final_score=0.8),
        ]

        ordered = orderer.order(
            candidates,
            ActiveState(),
            {},
            allow_popularity=False,
        )

        self.assertEqual(ordered[0].parent_asin, "rare")
        self.assertEqual(
            ordered[1].raw_scores["ordering_popularity_bonus"],
            0.0,
        )


if __name__ == "__main__":
    unittest.main()
