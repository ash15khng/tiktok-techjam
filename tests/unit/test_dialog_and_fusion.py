from __future__ import annotations

import unittest

from submission.src.catalog.models import CatalogSearchResult
from submission.src.dialog.models import SessionState
from submission.src.dialog.reducer import StateReducer
from submission.src.dialog.store import SessionStore
from submission.src.retrieval.fusion import reciprocal_rank_fusion
from submission.src.understanding.interpreter import MessageInterpreter
from submission.src.understanding.models import Attribute, IntentFrame, SlotUpdate


class DialogAndFusionTest(unittest.TestCase):
    @staticmethod
    def _answer_frame(attribute: Attribute, operation: str, value: str) -> IntentFrame:
        return IntentFrame(
            raw_message=value,
            dialogue_acts=("answer",),
            slot_updates=(SlotUpdate(attribute, operation, value, value),),
            category_phrases=(),
            preference_phrases=() if operation == "set_any" else (value,),
            exclusions=(),
            override=False,
            negative_feedback=False,
            no_preference_attribute=attribute if operation == "set_any" else None,
        )

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

    def test_clarification_outcomes_update_the_session_posterior(self) -> None:
        reducer = StateReducer()
        answered = SessionState("answered", {}, last_ask_attribute="color")
        declined = SessionState("declined", {}, last_ask_attribute="color")

        reducer.apply(answered, self._answer_frame(Attribute.COLOR, "add", "cerulean"))
        reducer.apply(declined, self._answer_frame(Attribute.COLOR, "set_any", "any"))

        self.assertEqual(answered.clarification_outcomes, {"color": "answered"})
        self.assertEqual(declined.clarification_outcomes, {"color": "declined"})
        self.assertGreater(answered.answerability_posterior(0.5, strength=3.0), 0.5)
        self.assertLess(declined.answerability_posterior(0.5, strength=3.0), 0.5)

    def test_reset_clears_session_clarification_learning(self) -> None:
        sessions = SessionStore()
        state = sessions.reset("session", {})
        state.clarification_outcomes["material"] = "answered"

        replacement = sessions.reset("session", {})

        self.assertEqual(replacement.clarification_outcomes, {})


if __name__ == "__main__":
    unittest.main()
