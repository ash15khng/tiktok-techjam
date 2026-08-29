"""Unit tests for the understanding subsystem: rules, grounding, assessment, and interpreter."""

from __future__ import annotations

import unittest

from shopping_copilot.config import UnderstandingConfig
from shopping_copilot.dialog.models import ActiveState, DialogueContext
from shopping_copilot.understanding.assessment import NeedAssessor
from shopping_copilot.understanding.grounding import (
    CatalogEntityLinker,
    CatalogTrie,
    build_default_trie,
)
from shopping_copilot.understanding.interpreter import MessageInterpreter
from shopping_copilot.understanding.models import Attribute, Relation
from shopping_copilot.understanding.rules import (
    detect_dialogue_acts,
    determine_modality_strength,
    extract_budget_slots,
    extract_negation_spans,
    extract_size_slots,
)


class TestUnderstandingRules(unittest.TestCase):
    def setUp(self) -> None:
        self.config = UnderstandingConfig()

    def test_budget_lte_extraction(self) -> None:
        slots = extract_budget_slots("I need a jacket under $50.", turn=1, config=self.config)
        self.assertEqual(len(slots), 1)
        self.assertEqual(slots[0].attribute, Attribute.BUDGET)
        self.assertEqual(slots[0].relation, Relation.LTE)
        self.assertEqual(slots[0].normalized_values, ("50.0",))

    def test_budget_gte_extraction(self) -> None:
        slots = extract_budget_slots("Budget must be at least $30.", turn=1, config=self.config)
        self.assertEqual(len(slots), 1)
        self.assertEqual(slots[0].attribute, Attribute.BUDGET)
        self.assertEqual(slots[0].relation, Relation.GTE)
        self.assertEqual(slots[0].normalized_values, ("30.0",))

    def test_budget_range_extraction(self) -> None:
        slots = extract_budget_slots("Looking for something between $25 and $75.", turn=1, config=self.config)
        self.assertEqual(len(slots), 1)
        self.assertEqual(slots[0].attribute, Attribute.BUDGET)
        self.assertEqual(slots[0].relation, Relation.RANGE)
        self.assertEqual(slots[0].normalized_values, ("25.0", "75.0"))

    def test_budget_approximate_extraction(self) -> None:
        slots = extract_budget_slots("budget around $50", turn=1, config=self.config)
        self.assertEqual(len(slots), 1)
        self.assertEqual(slots[0].attribute, Attribute.BUDGET)
        self.assertEqual(slots[0].relation, Relation.RANGE)
        self.assertEqual(slots[0].normalized_values, ("40.0", "60.0"))

    def test_size_extraction(self) -> None:
        slots = extract_size_slots("I wear size 10 wide", turn=1, config=self.config)
        self.assertEqual(len(slots), 1)
        self.assertEqual(slots[0].attribute, Attribute.SIZE)
        self.assertEqual(slots[0].normalized_values, ("10 wide",))

        alpha_slots = extract_size_slots("Looking for a medium dress", turn=1, config=self.config)
        self.assertEqual(len(alpha_slots), 1)
        self.assertEqual(alpha_slots[0].attribute, Attribute.SIZE)
        self.assertEqual(alpha_slots[0].normalized_values, ("m",))

    def test_negation_scope_extraction(self) -> None:
        spans = extract_negation_spans("I want blue, but not black or red, please.")
        self.assertTrue(any("black or red" in span[0] for span in spans))

    def test_dialogue_act_detection(self) -> None:
        self.assertIn("override", detect_dialogue_acts("Actually, ignore my earlier preference."))
        self.assertIn("indifference", detect_dialogue_acts("I don't have a preference; use your judgment."))
        self.assertIn("explore", detect_dialogue_acts("I'm looking for running shoes, but I'm still exploring."))
        self.assertIn("commit", detect_dialogue_acts("A key requirement is: 100% cotton."))

    def test_modality_strength(self) -> None:
        self.assertEqual(determine_modality_strength("It must be waterproof"), "hard")
        self.assertEqual(determine_modality_strength("I would like blue if possible"), "soft")


class TestGroundingAndTrie(unittest.TestCase):
    def setUp(self) -> None:
        self.trie = build_default_trie()
        self.config = UnderstandingConfig()
        self.linker = CatalogEntityLinker(self.config)

    def test_trie_longest_match(self) -> None:
        matches = self.trie.scan("I need a navy blue organic cotton running shirt")
        found = {attr: val for attr, val, _, _ in matches}
        self.assertEqual(found.get(Attribute.COLOR), "navy")
        self.assertEqual(found.get(Attribute.MATERIAL), "organic cotton")
        self.assertEqual(found.get(Attribute.USE_CASE), "running")
        self.assertEqual(found.get(Attribute.CATEGORY), "shirts")

    def test_fuzzy_linker_exact_or_close(self) -> None:
        val, score, _ = self.linker.link_span("coton", Attribute.MATERIAL)
        # Should link to cotton with reasonable score
        self.assertEqual(val, "cotton")
        self.assertGreaterEqual(score, 0.80)


class TestNeedAssessor(unittest.TestCase):
    def setUp(self) -> None:
        self.assessor = NeedAssessor()
        self.interpreter = MessageInterpreter()

    def test_buying_high_focus_score(self) -> None:
        msg = "I'm looking for running shoes. A key requirement is: 100% leather under $60."
        frame = self.interpreter.parse(msg)
        state = ActiveState(
            category="running shoes",
            constraints=tuple(
                # Map extracted slots to active constraints
                c for c in frame.slot_updates if c.operation in ("add", "set")
            ),
        )
        assessment = self.assessor.assess(state, frame)
        self.assertGreater(assessment.focus_score, 0.60)
        self.assertIn(assessment.decision_stage, ("narrowing", "deciding"))

    def test_browsing_exploring_decision_stage(self) -> None:
        msg = "I'm looking for clothing, but I'm still exploring."
        frame = self.interpreter.parse(msg)
        state = ActiveState(category="clothing")
        assessment = self.assessor.assess(state, frame)
        self.assertEqual(assessment.decision_stage, "exploring")
        self.assertGreaterEqual(assessment.exploration, 0.60)


class TestMessageInterpreter(unittest.TestCase):
    def setUp(self) -> None:
        self.interpreter = MessageInterpreter()

    def test_parse_structured_prefixes(self) -> None:
        msg = "color: navy; material: cotton; budget: under 40"
        frame = self.interpreter.parse(msg)
        attrs = {s.attribute for s in frame.slot_updates}
        self.assertIn(Attribute.COLOR, attrs)
        self.assertIn(Attribute.MATERIAL, attrs)
        self.assertIn(Attribute.BUDGET, attrs)

    def test_contextual_elliptical_reply(self) -> None:
        context = DialogueContext(
            active_state=ActiveState(),
            last_ask_attribute=Attribute.COLOR,
            turn=2,
        )
        frame = self.interpreter.parse("navy blue", context=context)
        self.assertEqual(len(frame.slot_updates), 1)
        self.assertEqual(frame.slot_updates[0].attribute, Attribute.COLOR)
        self.assertEqual(frame.slot_updates[0].normalized_values, ("navy",))


if __name__ == "__main__":
    unittest.main()

