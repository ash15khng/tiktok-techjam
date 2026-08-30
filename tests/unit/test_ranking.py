from __future__ import annotations

import unittest
from shopping_copilot.catalog.models import PriceValue, ProductRecord
from shopping_copilot.dialog.models import ActiveConstraint
from shopping_copilot.indexing.store import CatalogIndex
from shopping_copilot.ranking.belief import compute_candidate_belief, compute_top10_confidence
from shopping_copilot.ranking.constraints import evaluate_constraint
from shopping_copilot.ranking.reranker import LightweightReranker
from shopping_copilot.retrieval.models import CandidateEvidence, RetrievalRequest
from shopping_copilot.understanding.models import Attribute, Relation


def _make_prod(asin: str, title: str, material: str | None, color: str | None, price_val: float | None) -> ProductRecord:
    price = PriceValue(lower=price_val, upper=price_val, kind="exact" if price_val is not None else "unknown")
    attributes = {}
    if material:
        attributes["material"] = frozenset([material])
    if color:
        attributes["color"] = frozenset([color])
    return ProductRecord(
        parent_asin=asin,
        raw={"parent_asin": asin, "title": title},
        search_fields={"title": title, "categories": "apparel", "features": "", "details": "", "store": "", "description": ""},
        categories=("apparel",),
        attributes=attributes,
        attribute_evidence={},
        price=price,
        average_rating=4.5,
        rating_number=50,
        field_presence=frozenset(["title"]),
    )


class TestRankingSubsystem(unittest.TestCase):
    def setUp(self) -> None:
        self.records = [
            _make_prod("P1", "Cotton Black Shirt", "cotton", "black", 20.0),
            _make_prod("P2", "Polyester Black Shirt", "polyester", "black", 15.0),
            _make_prod("P3", "Mystery Shirt", None, "black", None),  # missing material and price
        ]
        self.catalog_index = CatalogIndex()
        self.catalog_index.build_from_records(self.records)
        self.reranker = LightweightReranker(self.catalog_index)

    def test_tri_state_constraint_evaluation(self) -> None:
        cotton_req = ActiveConstraint(
            attribute=Attribute.MATERIAL,
            relation=Relation.EQ,
            values=("cotton",),
            strength="hard",
            source_turn=1,
            raw_span="cotton",
        )

        # P1 has cotton -> match
        self.assertEqual(evaluate_constraint(self.records[0], cotton_req), "match")
        # P2 has polyester -> contradiction
        self.assertEqual(evaluate_constraint(self.records[1], cotton_req), "contradiction")
        # P3 has no material data -> unknown (never contradiction!)
        self.assertEqual(evaluate_constraint(self.records[2], cotton_req), "unknown")

    def test_reranker_demotes_hard_contradiction(self) -> None:
        req = RetrievalRequest(
            category="apparel",
            active_constraints=(
                ActiveConstraint(attribute=Attribute.MATERIAL, relation=Relation.EQ, values=("cotton",), strength="hard", source_turn=1, raw_span="cotton"),
            ),
            exclusions=(),
            product_terms=("shirt",),
            residual_terms=(),
            raw_phrases=(),
            profile_preferences=(),
            turns_remaining=9,
        )

        ev_map = {
            "P1": CandidateEvidence(parent_asin="P1", rrf_score=0.8),
            "P2": CandidateEvidence(parent_asin="P2", rrf_score=1.0),  # higher RRF but hard contradiction (polyester != cotton)
            "P3": CandidateEvidence(parent_asin="P3", rrf_score=0.5),  # unknown material
        }

        reranked = self.reranker.rerank(ev_map, req, top_k=3)
        asins = [ev.parent_asin for ev in reranked]

        # P1 (clean match) and P3 (clean unknown) must be ranked ahead of P2 (hard contradiction)
        self.assertEqual(asins[0], "P1")
        self.assertEqual(asins[1], "P3")
        self.assertEqual(asins[2], "P2")

    def test_candidate_belief_and_confidence(self) -> None:
        beliefs = compute_candidate_belief([1.0, 0.8, 0.2])
        self.assertEqual(len(beliefs), 3)
        self.assertAlmostEqual(sum(beliefs), 1.0, places=5)
        self.assertGreater(beliefs[0], beliefs[1])

        conf = compute_top10_confidence(top10_belief_mass=0.9, generator_agreement=0.8)
        self.assertTrue(0.0 <= conf <= 1.0)


if __name__ == "__main__":
    unittest.main()

