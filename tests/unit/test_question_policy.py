from __future__ import annotations

import unittest

from submission.src.config import AgentConfig
from submission.src.dialog.models import ActiveState, SessionState
from submission.src.dialog.policy import QuestionPolicy
from submission.src.retrieval.models import RetrievalAssessment


class QuestionPolicyTest(unittest.TestCase):
    def test_answerability_cannot_repeat_an_already_asked_attribute(self) -> None:
        class Attributes:
            @staticmethod
            def representative_value(parent_asin: str, attribute: str) -> str | None:
                values = {"A": "red", "B": "blue"}
                return values.get(parent_asin) if attribute == "color" else None

            @staticmethod
            def baseline_answerability(attribute: str) -> float:
                return 1.0

        class Store:
            attributes = Attributes()

        active = ActiveState(asked_attributes=["color"])
        state = SessionState("session", {}, active=active)
        candidates = [
            type("Candidate", (), {"parent_asin": "A"})(),
            type("Candidate", (), {"parent_asin": "B"})(),
        ]

        decision = QuestionPolicy(Store(), AgentConfig()).choose(
            state,
            candidates,
            RetrievalAssessment(2, 0.0, 0.0),
            turn=2,
        )

        self.assertNotEqual(decision.ask_attribute, "color")

    def test_unanswered_specific_question_uses_one_broad_recovery(self) -> None:
        active = ActiveState(
            suppressed_attributes={"feature"},
            asked_attributes=["feature"],
        )
        state = SessionState(
            session_id="session",
            customer_profile={},
            active=active,
            last_ask_attribute="feature",
        )
        assessment = RetrievalAssessment(
            candidate_count=100,
            generator_agreement=0.1,
            top10_stability=0.2,
        )

        decision = QuestionPolicy(object(), AgentConfig()).choose(state, [], assessment, turn=2)

        self.assertEqual(decision.ask_attribute, "other")
        self.assertEqual(decision.reason, "unanswered_question_recovery")

    def test_broad_recovery_is_not_repeated(self) -> None:
        active = ActiveState(
            suppressed_attributes={"feature"},
            asked_attributes=["feature", "other"],
        )
        state = SessionState(
            session_id="session",
            customer_profile={},
            active=active,
            last_ask_attribute="feature",
        )
        assessment = RetrievalAssessment(0, 0.0, 0.0)

        decision = QuestionPolicy(object(), AgentConfig()).choose(state, [], assessment, turn=2)

        self.assertNotEqual(decision.ask_attribute, "other")


if __name__ == "__main__":
    unittest.main()
