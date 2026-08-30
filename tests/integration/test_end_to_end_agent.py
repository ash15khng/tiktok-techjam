from __future__ import annotations

import unittest
from pathlib import Path

from starter.agent import Agent


class TestEndToEndAgent(unittest.TestCase):
    CATALOG_PATH = Path("data/catalog.jsonl")

    @unittest.skipUnless(CATALOG_PATH.is_file(), "data/catalog.jsonl is required for integration test")
    def test_multi_turn_conversation_flow(self) -> None:
        agent = Agent(self.CATALOG_PATH)
        session_id = "test_session_001"
        user_profile = {
            "summary": "Frequent shopper looking for durable apparel",
            "preference_tags": ["leather", "black", "durable"],
        }

        # Reset session
        agent.reset(session_id, user_profile)

        # Turn 1: Exploratory query
        res1 = agent.respond(session_id, "I'm looking for a nice jacket", turn=1, top_k=10)
        self.assertIsInstance(res1, dict)
        self.assertIn("message", res1)
        self.assertIn("recommendations", res1)
        self.assertEqual(len(res1["recommendations"]), 10)

        # Turn 2: Customer provides material clarification
        res2 = agent.respond(session_id, "I prefer genuine leather", turn=2, top_k=10)
        self.assertEqual(len(res2["recommendations"]), 10)

        # Turn 3: Customer specifies budget and color
        res3 = agent.respond(session_id, "Black color, under $200", turn=3, top_k=10)
        self.assertEqual(len(res3["recommendations"]), 10)

        # Turn 4: Customer overrides color
        res4 = agent.respond(session_id, "Actually, ignore black. I want brown instead.", turn=4, top_k=10)
        self.assertEqual(len(res4["recommendations"]), 10)


if __name__ == "__main__":
    unittest.main()

