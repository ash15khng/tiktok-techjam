from __future__ import annotations

import unittest

from submission.src.config import MVPConfig
from submission.src.dialog.models import ActiveState
from submission.src.retrieval.models import RetrievalAssessment
from submission.src.understanding.escalation import SemanticEscalationPolicy
from submission.src.understanding.interpreter import MessageInterpreter


class SemanticEscalationPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = SemanticEscalationPolicy(MVPConfig())
        self.interpreter = MessageInterpreter()

    def decide(self, message: str, active: ActiveState, stability: float):
        frame = self.interpreter.parse_deterministic(message, last_ask_attribute=None)
        return self.policy.decide(
            frame,
            active,
            RetrievalAssessment(200, stability / 2.5, stability),
        )

    def test_missing_category_escalates_a_substantive_turn(self) -> None:
        decision = self.decide(
            "Something I can throw in a backpack for a wet and windy commute.",
            ActiveState(preference_phrases=["wet and windy commute"]),
            0.8,
        )

        self.assertTrue(decision.should_call)
        self.assertEqual(decision.reason, "missing_category")

    def test_ambiguous_category_escalates_when_retrieval_is_unstable(self) -> None:
        frame = self.interpreter.parse_deterministic(
            "After work I want to slide into something fluffy at home, with open toes.",
            last_ask_attribute=None,
        )
        active = ActiveState(category_phrases=list(frame.category_phrases))

        decision = self.policy.decide(frame, active, RetrievalAssessment(200, 0.1, 0.25))

        self.assertTrue(decision.should_call)
        self.assertEqual(decision.reason, "ambiguous_category")

    def test_stable_explicit_category_skips_semantics(self) -> None:
        frame = self.interpreter.parse_deterministic(
            "I'm looking for waterproof hiking boots.",
            last_ask_attribute=None,
        )
        active = ActiveState(category_phrases=list(frame.category_phrases))

        decision = self.policy.decide(frame, active, RetrievalAssessment(200, 0.3, 0.75))

        self.assertFalse(decision.should_call)
        self.assertEqual(decision.reason, "deterministic_retrieval_sufficient")

    def test_exact_top_product_evidence_skips_even_when_routes_disagree(self) -> None:
        frame = self.interpreter.parse_deterministic(
            "I'm looking for walking shoes. Lightweight responsive cushioning.",
            last_ask_attribute=None,
        )
        active = ActiveState(
            category_phrases=list(frame.category_phrases),
            preference_phrases=list(frame.preference_phrases),
        )

        decision = self.policy.decide(
            frame,
            active,
            RetrievalAssessment(200, 0.01, 0.025),
            top_exact_preference_match=True,
        )

        self.assertFalse(decision.should_call)
        self.assertEqual(decision.reason, "exact_top_product_evidence")

    def test_short_contextual_reply_never_escalates(self) -> None:
        decision = self.decide("blue/", ActiveState(), 0.0)

        self.assertFalse(decision.should_call)
        self.assertEqual(decision.reason, "short_or_contextual")

    def test_unseen_subjective_words_escalate_from_fallback_and_instability(self) -> None:
        frame = self.interpreter.parse_deterministic(
            "I need boots. They should feel zephyric yet boardroom-ready all day.",
            last_ask_attribute=None,
        )
        active = ActiveState(
            category_phrases=list(frame.category_phrases),
            preference_phrases=list(frame.preference_phrases),
        )

        decision = self.policy.decide(
            frame,
            active,
            RetrievalAssessment(200, 0.01, 0.025),
        )

        self.assertTrue(decision.should_call)
        self.assertEqual(decision.reason, "difficult_language_low_stability")


if __name__ == "__main__":
    unittest.main()
