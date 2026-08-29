from __future__ import annotations

import unittest

from shopping_copilot.config import MVPConfig
from shopping_copilot.dialog.models import ActiveState, SessionState
from shopping_copilot.dialog.policy import QuestionPolicy
from shopping_copilot.retrieval.models import RetrievalAssessment


class QuestionPolicyTest(unittest.TestCase):
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

        decision = QuestionPolicy(object(), MVPConfig()).choose(state, [], assessment, turn=2)

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

        decision = QuestionPolicy(object(), MVPConfig()).choose(state, [], assessment, turn=2)

        self.assertNotEqual(decision.ask_attribute, "other")


if __name__ == "__main__":
    unittest.main()
