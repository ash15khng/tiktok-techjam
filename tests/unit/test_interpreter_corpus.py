"""Interpreter scenario corpus covering diverse eCommerce utterances and edge cases."""

from __future__ import annotations

import unittest

from shopping_copilot.dialog.models import ActiveState, DialogueContext
from shopping_copilot.understanding.interpreter import MessageInterpreter
from shopping_copilot.understanding.models import Attribute, Relation


class TestInterpreterCorpus(unittest.TestCase):
    def setUp(self) -> None:
        self.interpreter = MessageInterpreter()

    def test_corpus_product_and_need_requests(self) -> None:
        test_cases = [
            # Utterance, Expected Attribute, Expected Value/Op
            ("I need black running shoes under $60", Attribute.COLOR, "black"),
            ("Looking for breathable linen shirts", Attribute.MATERIAL, "linen"),
            ("Looking for 100% cotton hoodie", Attribute.MATERIAL, "cotton"),
            ("Need winter boots with non-slip sole", Attribute.FEATURE, "non-slip"),
            ("Men's casual slim fit denim jeans", Attribute.STYLE, "slim fit"),
            ("Looking for waterproof hiking boots", Attribute.FEATURE, "waterproof"),
            ("Searching for casual sneakers size 10", Attribute.SIZE, "10"),
            ("I want a floral maxi dress for summer", Attribute.USE_CASE, "summer"),
            ("Looking for a warm fleece jacket with zipper", Attribute.STYLE, "zipper closure"),
            ("Need lightweight quick dry workout shorts", Attribute.FEATURE, "quick dry"),
        ]

        for utterance, expected_attr, expected_val in test_cases:
            with self.subTest(utterance=utterance):
                frame = self.interpreter.parse(utterance)
                found = any(
                    s.attribute == expected_attr and expected_val in s.normalized_values
                    for s in frame.slot_updates
                )
                self.assertTrue(
                    found,
                    f"Failed to find {expected_attr}={expected_val} in {frame.slot_updates} for utterance '{utterance}'",
                )

    def test_corpus_negation_and_exclusions(self) -> None:
        test_cases = [
            ("I want boots, but not leather please", Attribute.MATERIAL, "leather"),
            ("Looking for shirts, avoid synthetic fabric", Attribute.MATERIAL, "fabric"),
            ("Anything but black sneakers", Attribute.COLOR, "black"),
            ("Without zipper closure", Attribute.STYLE, "zipper closure"),
        ]
        for utterance, expected_attr, expected_val in test_cases:
            with self.subTest(utterance=utterance):
                frame = self.interpreter.parse(utterance)
                excluded = any(
                    s.attribute == expected_attr
                    and s.operation == "exclude"
                    and expected_val in s.normalized_values
                    for s in frame.slot_updates
                )
                self.assertTrue(
                    excluded,
                    f"Expected exclusion of {expected_attr}={expected_val} in {frame.slot_updates} for '{utterance}'",
                )

    def test_corpus_dialogue_operations(self) -> None:
        # Override
        frame_override = self.interpreter.parse(
            "Actually, ignore my earlier choice. What I need is: 100% merino wool."
        )
        self.assertIn("override", frame_override.dialogue_acts)
        wool_slot = [s for s in frame_override.slot_updates if s.attribute == Attribute.MATERIAL]
        self.assertTrue(wool_slot)
        self.assertEqual(wool_slot[0].operation, "replace")

        # Indifference / set_any
        ctx = DialogueContext(active_state=ActiveState(), last_ask_attribute=Attribute.SIZE, turn=2)
        frame_indiff = self.interpreter.parse("Either size is fine, please use your judgment.", context=ctx)
        self.assertIn("indifference", frame_indiff.dialogue_acts)
        set_any_slots = [s for s in frame_indiff.slot_updates if s.operation == "set_any"]
        self.assertTrue(set_any_slots)
        self.assertEqual(set_any_slots[0].attribute, Attribute.SIZE)

    def test_corpus_numeric_budgets(self) -> None:
        cases = [
            ("budget under $45", Relation.LTE, ("45.0",)),
            ("budget at least $100", Relation.GTE, ("100.0",)),
            ("price between $20 and $40", Relation.RANGE, ("20.0", "40.0")),
            ("budget around $50", Relation.RANGE, ("40.0", "60.0")),
            ("budget: <= 75.50", Relation.LTE, ("75.5",)),
        ]
        for utterance, expected_rel, expected_vals in cases:
            with self.subTest(utterance=utterance):
                frame = self.interpreter.parse(utterance)
                budget_slots = [s for s in frame.slot_updates if s.attribute == Attribute.BUDGET]
                self.assertTrue(budget_slots, f"No budget slot found in '{utterance}'")
                self.assertEqual(budget_slots[0].relation, expected_rel)
                self.assertEqual(budget_slots[0].normalized_values, expected_vals)


if __name__ == "__main__":
    unittest.main()

