from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from submission.src.agent import ShoppingAgent
from submission.src.config import AgentConfig
from submission.src.contracts import (
    ALLOWED_ATTRIBUTES,
    SemanticInterpretation,
    SemanticSlotHypothesis,
)
from starter.agent import Agent


PRODUCTS = (
    {
        "parent_asin": "A",
        "title": "Red cotton road running shoes",
        "features": ["breathable cotton upper", "road running"],
        "description": [],
        "price": 50.0,
        "categories": ["Shoes", "Running Shoes"],
        "details": {"Color": "Red", "Material": "Cotton", "Occasion": "Wedding"},
        "average_rating": 4.5,
        "rating_number": 100,
        "store": "Example",
    },
    {
        "parent_asin": "B",
        "title": "Blue leather hiking boots",
        "features": ["full grain leather", "hiking traction"],
        "description": [],
        "price": 90.0,
        "categories": ["Shoes", "Hiking Boots"],
        "details": {"Color": "Blue", "Material": "Leather"},
        "average_rating": 4.5,
        "rating_number": 100,
        "store": "Example",
    },
    {
        "parent_asin": "C",
        "title": "Black cotton shirt",
        "features": ["casual shirt"],
        "description": [],
        "price": 25.0,
        "categories": ["Clothing", "Shirts"],
        "details": {"Color": "Black", "Material": "Cotton"},
        "average_rating": 4.0,
        "rating_number": 20,
        "store": "Example",
    },
)


class AgentIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        catalog_path = Path(self.temporary_directory.name) / "catalog.jsonl"
        catalog_path.write_text(
            "".join(json.dumps(product) + "\n" for product in PRODUCTS),
            encoding="utf-8",
        )
        self.agent = Agent(catalog_path)
        self.agent.reset("session", {"preference_tags": []})

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_response_obeys_contract_and_ranks_matching_product(self) -> None:
        response = self.agent.respond(
            "session",
            "I'm looking for running shoes. A key requirement is: cotton.",
            1,
            10,
        )

        ranked = [item["parent_asin"] for item in response["recommendations"]]
        self.assertEqual(ranked[0], "A")
        self.assertLessEqual(len(ranked), 10)
        self.assertEqual(len(ranked), len(set(ranked)))
        self.assertTrue(
            response["ask_attribute"] is None
            or response["ask_attribute"] in ALLOWED_ATTRIBUTES
        )

    def test_override_replaces_stale_opening_preference(self) -> None:
        self.agent.respond("session", "I'm looking for shoes. cotton", 1, 10)
        response = self.agent.respond(
            "session",
            "Actually, ignore my earlier preference. What I need is: leather.",
            2,
            10,
        )

        self.assertEqual(response["recommendations"][0]["parent_asin"], "B")
        active = self.agent._agent.sessions.get("session").active
        self.assertNotIn("cotton", " ".join(active.preference_phrases).casefold())

    def test_boundary_reply_suppresses_repeated_attribute(self) -> None:
        self.agent.respond("session", "I'm looking for shoes.", 1, 10)
        self.agent.respond(
            "session",
            "I don't have a preference for color; please use your judgment.",
            2,
            10,
        )

        active = self.agent._agent.sessions.get("session").active
        self.assertIn("color", active.suppressed_attributes)

    def test_additional_preference_decline_preserves_existing_value(self) -> None:
        self.agent.respond("session", "I'm looking for shoes. cotton", 1, 10)
        state = self.agent._agent.sessions.get("session")
        state.last_ask_attribute = "material"

        self.agent.respond(
            "session",
            "I don't have an additional preference for material.",
            2,
            10,
        )

        self.assertIn("cotton", state.active.preference_phrases)
        self.assertIn("material", state.active.suppressed_attributes)

    def test_next_turn_does_not_repeat_shown_products_when_alternatives_exist(self) -> None:
        first = self.agent.respond("session", "I'm looking for shoes.", 1, 1)
        second = self.agent.respond(
            "session",
            "Those options are not quite right yet. Ask me about one specific attribute.",
            2,
            1,
        )

        first_ids = {item["parent_asin"] for item in first["recommendations"]}
        second_ids = {item["parent_asin"] for item in second["recommendations"]}
        self.assertFalse(first_ids & second_ids)

    def test_duplicate_turn_returns_cached_response_without_mutating_state(self) -> None:
        first = self.agent.respond("session", "I'm looking for red shoes.", 1, 10)
        state = self.agent._agent.sessions.get("session")

        duplicate = self.agent.respond("session", "Actually make them black.", 1, 10)

        self.assertEqual(duplicate, first)
        self.assertEqual(state.turn_count, 1)
        self.assertNotIn("black", state.active.query_terms())
        self.assertEqual(len(state.responses_by_turn), 1)
        self.assertEqual(
            self.agent._agent.diagnostics()["runtime"]["cached_turn_responses"],
            1,
        )

    def test_component_failure_reuses_last_successful_recommendations(self) -> None:
        first = self.agent.respond("session", "I'm looking for shoes.", 1, 2)
        expected = [item["parent_asin"] for item in first["recommendations"]]

        def fail_retrieval(*_args, **_kwargs):
            raise RuntimeError("synthetic retrieval failure")

        self.agent._agent.retriever.retrieve = fail_retrieval
        recovered = self.agent.respond("session", "Something different.", 2, 2)

        self.assertEqual(
            [item["parent_asin"] for item in recovered["recommendations"]],
            expected,
        )
        self.assertEqual(recovered["ask_attribute"], None)
        self.assertEqual(
            self.agent._agent.diagnostics()["runtime"]["fallback_responses"],
            1,
        )

    def test_late_turn_returns_latest_response_without_replaying_state(self) -> None:
        first = self.agent.respond("session", "I'm looking for shoes.", 1, 10)
        second = self.agent.respond("session", "Prefer leather.", 2, 10)
        state = self.agent._agent.sessions.get("session")

        late = self.agent.respond("session", "This must not be interpreted.", 0, 10)

        self.assertNotEqual(first, second)
        self.assertEqual(late, second)
        self.assertEqual(state.turn_count, 2)
        self.assertNotIn("interpreted", state.active.query_terms())
        self.assertEqual(
            self.agent._agent.diagnostics()["runtime"]["out_of_order_responses"],
            1,
        )

    def test_real_user_budget_and_exclusion_affect_the_end_to_end_list(self) -> None:
        response = self.agent.respond(
            "session",
            "I'm looking for shoes under $60, preferably red, no leather.",
            1,
            10,
        )

        self.assertEqual(response["recommendations"][0]["parent_asin"], "A")
        active = self.agent._agent.sessions.get("session").active
        self.assertEqual(active.slot_values["budget"], ["under $60"])
        self.assertIn("leather", active.exclusions)

    def test_short_reply_is_grounded_by_the_previous_question(self) -> None:
        state = self.agent._agent.sessions.get("session")
        state.last_ask_attribute = "brand"

        self.agent.respond("session", "Example", 1, 10)

        self.assertEqual(state.active.slot_values["brand"], ["Example"])

    def test_semantic_rewrite_and_grounded_feature_affect_live_retrieval_state(self) -> None:
        class StaticSemanticParser:
            def interpret(self, message: str, context: str) -> SemanticInterpretation:
                return SemanticInterpretation(
                    query_rewrites=("breathable cotton formal wedding shoes",),
                    subjective_needs=("comfortable in humidity",),
                    slot_hypotheses=(
                        SemanticSlotHypothesis("feature", "breathable", 0.70, "humid"),
                    ),
                    prompt_tokens=15,
                    completion_tokens=6,
                )

        catalog_path = Path(self.temporary_directory.name) / "catalog.jsonl"
        agent = ShoppingAgent(catalog_path, semantic_parser=StaticSemanticParser())
        agent.reset("semantic", {"preference_tags": []})

        response = agent.respond(
            "semantic",
            "Something polished but comfortable for a humid outdoor wedding.",
            1,
            10,
        )

        active = agent.sessions.get("semantic").active
        self.assertIn("breathable cotton formal wedding shoes", active.search_rewrites)
        self.assertEqual(active.slot_values["feature"], ["breathable"])
        self.assertEqual(response["recommendations"][0]["parent_asin"], "A")
        self.assertEqual(response["usage"], {"prompt_tokens": 15, "completion_tokens": 6})
        self.assertEqual(agent.sessions.get("semantic").turn_count, 1)
        self.assertEqual(agent.diagnostics()["semantic_escalation"]["semantic_applied"], 1)

    def test_compound_corrections_preserve_unrelated_constraints(self) -> None:
        messages = (
            "im looking for red shoes",
            "size 10",
            "no budget, actually make the shoes black",
            "for casual wear, actually i want it dont care about colour too",
        )
        for turn, message in enumerate(messages, 1):
            self.agent.respond("session", message, turn, 10)

        active = self.agent._agent.sessions.get("session").active
        self.assertEqual(active.category_phrases, ["shoes"])
        self.assertEqual(active.slot_values["size"], ["size 10"])
        self.assertEqual(active.slot_values["use_case"], ["casual wear"])
        self.assertNotIn("color", active.slot_values)
        self.assertNotIn("budget", active.slot_values)
        self.assertEqual(active.suppressed_attributes, {"budget", "color"})
        self.assertNotIn("red", active.query_terms())
        self.assertNotIn("black", active.query_terms())

    def test_semantic_calls_are_bounded_per_session(self) -> None:
        class EmptyCountingParser:
            calls = 0

            def interpret(self, message: str, context: str) -> SemanticInterpretation:
                self.calls += 1
                return SemanticInterpretation()

        parser = EmptyCountingParser()
        catalog_path = Path(self.temporary_directory.name) / "catalog.jsonl"
        agent = ShoppingAgent(
            catalog_path,
            config=AgentConfig(semantic_max_calls_per_session=1),
            semantic_parser=parser,
        )
        agent.reset("bounded", {})

        agent.respond("bounded", "Something comfortable that works after a long shift.", 1, 10)
        agent.respond("bounded", "Something polished that works for a formal event.", 2, 10)

        self.assertEqual(parser.calls, 1)
        self.assertEqual(agent.sessions.get("bounded").semantic_call_count, 1)


if __name__ == "__main__":
    unittest.main()
