from __future__ import annotations

import unittest
from shopping_copilot.catalog.models import PriceValue, ProductRecord
from shopping_copilot.dialog.models import ActiveConstraint, ActiveState
from shopping_copilot.indexing.store import CatalogIndex
from shopping_copilot.policy.question import QuestionPolicy
from shopping_copilot.retrieval.models import CandidateEvidence
from shopping_copilot.understanding.models import Attribute, Relation


def _make_item(asin: str, color: str, material: str) -> ProductRecord:
    return ProductRecord(
        parent_asin=asin,
        raw={"parent_asin": asin},
        search_fields={"title": f"{color} {material}", "categories": "apparel", "features": "", "details": "", "store": "", "description": ""},
        categories=("apparel",),
        attributes={
            "color": frozenset([color]),
            "material": frozenset([material]),
        },
        attribute_evidence={},
        price=PriceValue(lower=25.0, upper=25.0, kind="exact"),
        average_rating=4.5,
        rating_number=50,
        field_presence=frozenset(["title"]),
    )


class TestQuestionPolicy(unittest.TestCase):
    def setUp(self) -> None:
        self.records = [
            _make_item("P1", "black", "cotton"),
            _make_item("P2", "white", "cotton"),
            _make_item("P3", "red", "leather"),
            _make_item("P4", "blue", "leather"),
        ]
        self.catalog_index = CatalogIndex()
        self.catalog_index.build_from_records(self.records)
        self.policy = QuestionPolicy(self.catalog_index)
        self.candidates = [CandidateEvidence(parent_asin=p.parent_asin) for p in self.records]

    def test_turn_10_never_asks(self) -> None:
        state = ActiveState(turn=10)
        decision = self.policy.decide_action(
            active_state=state,
            candidate_evidence=self.candidates,
            turn=10,
            focus_score=0.5,
            asked_attributes_in_session=set(),
        )
        self.assertIsNone(decision.ask_attribute)
        self.assertEqual(len(decision.recommendations), 4)

    def test_suppressed_any_attribute_is_not_asked(self) -> None:
        # User explicitly stated ANY for color
        state = ActiveState(
            turn=1,
            any_attributes=frozenset([Attribute.COLOR]),
        )
        decision = self.policy.decide_action(
            active_state=state,
            candidate_evidence=self.candidates,
            turn=1,
            focus_score=0.5,
            asked_attributes_in_session=set(),
        )
        self.assertNotEqual(decision.ask_attribute, "color")

    def test_does_not_repeat_asked_attribute(self) -> None:
        state = ActiveState(turn=2)
        decision = self.policy.decide_action(
            active_state=state,
            candidate_evidence=self.candidates,
            turn=2,
            focus_score=0.5,
            asked_attributes_in_session={"color", "material"},
        )
        self.assertNotIn(decision.ask_attribute, ["color", "material"])


if __name__ == "__main__":
    unittest.main()

