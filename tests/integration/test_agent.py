from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from shopping_copilot.contracts import ALLOWED_ATTRIBUTES
from starter.agent import Agent


PRODUCTS = (
    {
        "parent_asin": "A",
        "title": "Red cotton road running shoes",
        "features": ["breathable cotton upper", "road running"],
        "description": [],
        "price": 50.0,
        "categories": ["Shoes", "Running Shoes"],
        "details": {"Color": "Red", "Material": "Cotton"},
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
        self.assertTrue(response["ask_attribute"] is None or response["ask_attribute"] in ALLOWED_ATTRIBUTES)

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


if __name__ == "__main__":
    unittest.main()
