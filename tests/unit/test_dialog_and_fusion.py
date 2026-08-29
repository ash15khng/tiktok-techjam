from __future__ import annotations

import unittest

from shopping_copilot.catalog.models import CatalogSearchResult
from shopping_copilot.dialog.models import SessionState
from shopping_copilot.dialog.reducer import StateReducer
from shopping_copilot.retrieval.fusion import reciprocal_rank_fusion
from shopping_copilot.understanding.interpreter import MessageInterpreter


class DialogAndFusionTest(unittest.TestCase):
    def test_override_removes_stale_preference_but_keeps_category(self) -> None:
        interpreter = MessageInterpreter()
        reducer = StateReducer()
        state = SessionState("session", {})
        first = interpreter.parse(
            "I'm looking for boots. I prefer suede.",
            last_ask_attribute=None,
            context="",
        )
        reducer.apply(state, first)
        override = interpreter.parse(
            "Actually, ignore my earlier preference. What I need is: leather.",
            last_ask_attribute="feature",
            context=state.active.context_snapshot(),
        )
        reducer.apply(state, override)

        self.assertEqual(state.active.category_phrases, ["boots"])
        self.assertEqual(state.active.preference_phrases, ["leather"])

    def test_override_keeps_later_confirmed_evidence(self) -> None:
        interpreter = MessageInterpreter()
        reducer = StateReducer()
        state = SessionState("session", {})
        reducer.apply(
            state,
            interpreter.parse(
                "I'm looking for belts. Buckle closure.",
                last_ask_attribute=None,
                context="",
            ),
        )
        reducer.apply(
            state,
            interpreter.parse(
                "For that, what matters is: Imported; Buckle closure.",
                last_ask_attribute="feature",
                context=state.active.context_snapshot(),
            ),
        )
        reducer.apply(
            state,
            interpreter.parse(
                "Actually, ignore my earlier preference. What I need is: leather.",
                last_ask_attribute="other",
                context=state.active.context_snapshot(),
            ),
        )

        self.assertEqual(state.active.preference_phrases, ["Imported", "leather"])

    def test_override_resets_recommendation_exposure(self) -> None:
        interpreter = MessageInterpreter()
        reducer = StateReducer()
        state = SessionState("session", {}, recommendation_exposure={"A", "B"})

        reducer.apply(
            state,
            interpreter.parse(
                "Actually, ignore my earlier preference. What I need is: leather.",
                last_ask_attribute="feature",
                context="",
            ),
        )

        self.assertEqual(state.recommendation_exposure, set())

    def test_rrf_combines_routes_and_retains_ranks(self) -> None:
        results = {
            "field": [CatalogSearchResult("A", -2.0), CatalogSearchResult("B", -1.0)],
            "title": [CatalogSearchResult("B", -3.0)],
        }

        fused = reciprocal_rank_fusion(results, {"field": 1.0, "title": 1.0}, k=60)

        self.assertEqual(fused[0].parent_asin, "B")
        self.assertEqual(fused[0].generator_ranks, {"field": 2, "title": 1})


if __name__ == "__main__":
    unittest.main()
