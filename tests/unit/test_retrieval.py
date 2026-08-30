from __future__ import annotations

import unittest
from shopping_copilot.catalog.models import PriceValue, ProductRecord
from shopping_copilot.dialog.models import ActiveConstraint
from shopping_copilot.indexing.store import CatalogIndex
from shopping_copilot.retrieval.assessment import RetrievalAssessor
from shopping_copilot.retrieval.attributes import AttributeCandidateGenerator
from shopping_copilot.retrieval.fusion import WeightedRRFFusion
from shopping_copilot.retrieval.lexical import FieldWeightedFTSGenerator, TitleFTSGenerator
from shopping_copilot.retrieval.models import RetrievalRequest
from shopping_copilot.retrieval.planner import RetrievalPlanner
from shopping_copilot.understanding.models import Attribute, Relation


def _make_sample_record(
    asin: str,
    title: str,
    category: str,
    material: str,
    color: str,
    price_val: float = 30.0,
) -> ProductRecord:
    price = PriceValue(lower=price_val, upper=price_val, kind="exact")
    search_fields = {
        "title": title.lower(),
        "categories": category.lower(),
        "features": f"{material} {color}",
        "details": "",
        "store": "BrandX",
        "description": "High quality product",
    }
    return ProductRecord(
        parent_asin=asin,
        raw={"parent_asin": asin, "title": title},
        search_fields=search_fields,
        categories=(category,),
        attributes={
            "material": frozenset([material.lower()]),
            "color": frozenset([color.lower()]),
        },
        attribute_evidence={},
        price=price,
        average_rating=4.5,
        rating_number=100,
        field_presence=frozenset(["title", "categories", "features"]),
    )


class TestRetrievalSubsystem(unittest.TestCase):
    def setUp(self) -> None:
        self.records = [
            _make_sample_record("ASIN1", "Men's Black Leather Jacket", "Jackets", "leather", "black", 120.0),
            _make_sample_record("ASIN2", "Women's Black Cotton T-Shirt", "Shirts", "cotton", "black", 25.0),
            _make_sample_record("ASIN3", "Casual Brown Leather Boots", "Shoes", "leather", "brown", 90.0),
            _make_sample_record("ASIN4", "Navy Blue Wool Winter Coat", "Jackets", "wool", "navy", 150.0),
        ]
        self.catalog_index = CatalogIndex()
        self.catalog_index.build_from_records(self.records)

        self.title_gen = TitleFTSGenerator(self.catalog_index)
        self.field_gen = FieldWeightedFTSGenerator(self.catalog_index)
        self.attr_gen = AttributeCandidateGenerator(self.catalog_index)
        self.fusion = WeightedRRFFusion()
        self.planner = RetrievalPlanner()
        self.assessor = RetrievalAssessor(self.catalog_index)

    def test_lexical_generators(self) -> None:
        req = RetrievalRequest(
            category="Jackets",
            active_constraints=(
                ActiveConstraint(attribute=Attribute.MATERIAL, relation=Relation.EQ, values=("leather",), strength="hard", source_turn=1, raw_span="leather"),
            ),
            exclusions=(),
            product_terms=("jacket",),
            residual_terms=(),
            raw_phrases=(),
            profile_preferences=(),
            turns_remaining=9,
        )

        title_res = self.title_gen.generate(req, limit=5)
        self.assertTrue(len(title_res) >= 1)
        self.assertEqual(title_res[0][0], "ASIN1")

        field_res = self.field_gen.generate(req, limit=5)
        self.assertTrue(len(field_res) >= 1)

    def test_attribute_generator_and_exclusions(self) -> None:
        req = RetrievalRequest(
            category=None,
            active_constraints=(
                ActiveConstraint(attribute=Attribute.MATERIAL, relation=Relation.EQ, values=("leather",), strength="hard", source_turn=1, raw_span="leather"),
            ),
            exclusions=(
                ActiveConstraint(attribute=Attribute.COLOR, relation=Relation.NEQ, values=("brown",), strength="hard", source_turn=1, raw_span="not brown"),
            ),
            product_terms=(),
            residual_terms=(),
            raw_phrases=(),
            profile_preferences=(),
            turns_remaining=8,
        )

        attr_res = self.attr_gen.generate(req, limit=5)
        asins = [a for a, _ in attr_res]
        self.assertIn("ASIN1", asins)
        self.assertNotIn("ASIN3", asins)  # ASIN3 is brown leather; excluded

    def test_rrf_fusion(self) -> None:
        gen_results = {
            "title_fts": [("ASIN1", 5.0), ("ASIN2", 3.0)],
            "field_fts": [("ASIN1", 10.0), ("ASIN3", 4.0)],
            "attribute_posting": [("ASIN1", 2.5), ("ASIN2", 1.0)],
        }
        weights = {"title_fts": 1.0, "field_fts": 1.0, "attribute_posting": 1.2}

        evidence = self.fusion.fuse(gen_results, weights)
        self.assertIn("ASIN1", evidence)
        self.assertIn("ASIN2", evidence)
        # ASIN1 is top across all generators, should have highest score
        self.assertEqual(evidence["ASIN1"].rrf_score, 1.0)
        self.assertGreater(evidence["ASIN1"].rrf_score, evidence["ASIN2"].rrf_score)

    def test_planner_blending(self) -> None:
        plan_focused = self.planner.plan(focus_score=1.0)
        self.assertEqual(plan_focused.generator_weights["attribute_posting"], 1.3)
        self.assertEqual(plan_focused.generator_weights["field_fts"], 0.8)

        plan_exploring = self.planner.plan(focus_score=0.0)
        self.assertEqual(plan_exploring.generator_weights["attribute_posting"], 0.9)
        self.assertEqual(plan_exploring.generator_weights["field_fts"], 1.0)

    def test_assessor_metrics(self) -> None:
        gen_results = {
            "gen1": [("ASIN1", 1.0), ("ASIN2", 0.5)],
            "gen2": [("ASIN1", 2.0), ("ASIN3", 1.5)],
        }
        agreement = self.assessor.compute_generator_agreement(gen_results)
        self.assertTrue(0.0 <= agreement <= 1.0)

        entropy = self.assessor.compute_category_entropy(["ASIN1", "ASIN2", "ASIN3"])
        self.assertTrue(0.0 <= entropy <= 1.0)


if __name__ == "__main__":
    unittest.main()

