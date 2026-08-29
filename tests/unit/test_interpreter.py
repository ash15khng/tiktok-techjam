from __future__ import annotations

import unittest

from shopping_copilot.contracts import SemanticInterpretation, SemanticSlotHypothesis
from shopping_copilot.understanding.interpreter import MessageInterpreter
from shopping_copilot.understanding.models import Attribute


class MessageInterpreterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.interpreter = MessageInterpreter()

    def parse(self, message: str, last_ask: str | None = None):
        return self.interpreter.parse(message, last_ask_attribute=last_ask, context="")

    def test_browsing_message_keeps_category_without_boilerplate(self) -> None:
        frame = self.parse("I'm looking for running shoes, but I'm still exploring.")

        self.assertEqual(frame.category_phrases, ("running shoes",))
        self.assertEqual(frame.preference_phrases, ())

    def test_constraint_payload_preserves_raw_feature_text(self) -> None:
        frame = self.parse("For that, what matters is: waterproof upper; non-slip sole.")

        self.assertEqual(frame.preference_phrases, ("waterproof upper", "non-slip sole"))

    def test_override_is_a_replacement_event(self) -> None:
        frame = self.parse("Actually, ignore my earlier preference. What I need is: leather.")

        self.assertTrue(frame.override)
        self.assertEqual(frame.slot_updates[0].operation, "replace")
        self.assertEqual(frame.slot_updates[0].attribute, Attribute.MATERIAL)

    def test_boundary_reply_uses_last_asked_attribute(self) -> None:
        frame = self.parse("I don't have a preference; please use your judgment.", "color")

        self.assertEqual(frame.no_preference_attribute, Attribute.COLOR)

    def test_real_user_compound_request_separates_category_budget_and_exclusion(self) -> None:
        frame = self.parse("I'm looking for running shoes under $100, preferably blue, no leather.")

        self.assertEqual(frame.category_phrases, ("running shoes",))
        self.assertIn("under $100", frame.preference_phrases)
        self.assertIn("blue", frame.preference_phrases)
        self.assertEqual(frame.exclusions, ("leather",))
        self.assertIn(Attribute.BUDGET, {update.attribute for update in frame.slot_updates})

    def test_compact_correction_removes_discourse_boilerplate(self) -> None:
        frame = self.parse("Actually, make it waterproof instead.")

        self.assertTrue(frame.override)
        self.assertEqual(frame.preference_phrases, ("waterproof",))

    def test_short_brand_reply_uses_the_last_clarification(self) -> None:
        frame = self.parse("Nike", "brand")

        self.assertEqual(frame.preference_phrases, ("Nike",))
        self.assertEqual(frame.slot_updates[0].attribute, Attribute.BRAND)
        self.assertEqual(frame.slot_updates[0].source, "contextual")

    def test_numeric_size_reply_uses_context_and_remains_searchable(self) -> None:
        frame = self.parse("7", "size")

        self.assertEqual(frame.preference_phrases, ("7",))
        self.assertEqual(frame.slot_updates[0].attribute, Attribute.SIZE)
        self.assertEqual(frame.slot_updates[0].source, "contextual")

    def test_bare_budget_reply_is_normalized_to_an_approximate_range(self) -> None:
        frame = self.parse("80", "budget")

        self.assertEqual(frame.preference_phrases, ("budget around $80",))
        self.assertEqual(frame.slot_updates[0].attribute, Attribute.BUDGET)

    def test_explicit_material_overrides_color_question_context(self) -> None:
        frame = self.parse("Leather is more important", "color")

        self.assertEqual(frame.slot_updates[0].attribute, Attribute.MATERIAL)
        self.assertEqual(frame.slot_updates[0].source, "explicit")

    def test_bare_no_declines_the_last_attribute(self) -> None:
        frame = self.parse("no", "color")

        self.assertEqual(frame.no_preference_attribute, Attribute.COLOR)
        self.assertEqual(frame.slot_updates[0].operation, "set_any")
        self.assertEqual(frame.slot_updates[0].source, "contextual")

    def test_bare_affirmation_does_not_become_search_evidence(self) -> None:
        frame = self.parse("yes", "color")

        self.assertEqual(frame.preference_phrases, ())
        self.assertEqual(frame.slot_updates, ())

    def test_short_category_reply_updates_category_phrases(self) -> None:
        frame = self.parse("boots", "category")

        self.assertEqual(frame.category_phrases, ("boots",))
        self.assertEqual(frame.slot_updates[0].attribute, Attribute.CATEGORY)

    def test_grounded_semantic_hints_become_soft_search_evidence(self) -> None:
        class StaticSemanticParser:
            def interpret(self, message: str, context: str) -> SemanticInterpretation:
                return SemanticInterpretation(
                    query_rewrites=("breathable formal wedding shoes",),
                    subjective_needs=("comfortable in humid weather",),
                    slot_hypotheses=(
                        SemanticSlotHypothesis("feature", "breathable", 0.70, "humid"),
                    ),
                    prompt_tokens=21,
                    completion_tokens=9,
                )

        interpreter = MessageInterpreter(StaticSemanticParser())
        frame = interpreter.parse(
            "Something polished but comfortable for a humid outdoor wedding.",
            last_ask_attribute=None,
            context="category=shoes",
        )

        self.assertEqual(frame.query_rewrites, ("breathable formal wedding shoes",))
        self.assertIn("breathable", frame.preference_phrases)
        semantic_updates = [update for update in frame.slot_updates if update.source == "semantic"]
        self.assertEqual(len(semantic_updates), 1)
        self.assertEqual(semantic_updates[0].attribute, Attribute.FEATURE)
        self.assertEqual(frame.prompt_tokens, 21)

    def test_deterministic_parse_defers_provider_until_forced_enrichment(self) -> None:
        class ForcedSemanticParser:
            calls = 0

            def interpret(self, message: str, context: str) -> SemanticInterpretation:
                raise AssertionError("normal language gate should not be used")

            def interpret_eligible(self, message: str, context: str) -> SemanticInterpretation:
                self.calls += 1
                return SemanticInterpretation(query_rewrites=("water resistant windbreaker commute",))

        provider = ForcedSemanticParser()
        interpreter = MessageInterpreter(provider)
        frame = interpreter.parse_deterministic(
            "Something for a wet and windy commute.",
            last_ask_attribute=None,
        )

        self.assertEqual(provider.calls, 0)
        enriched = interpreter.enrich_with_semantics(frame, context="", force=True)

        self.assertEqual(provider.calls, 1)
        self.assertEqual(enriched.query_rewrites, ("water resistant windbreaker commute",))


if __name__ == "__main__":
    unittest.main()
