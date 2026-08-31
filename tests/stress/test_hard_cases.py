from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests.stress.hard_evaluator import DEFAULT_CASES, load_cases


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class HardCaseFixtureTest(unittest.TestCase):
    def test_fixture_is_well_formed_and_targets_are_outside_public_set(self) -> None:
        fixture = load_cases()
        cases = fixture["cases"]
        self.assertGreaterEqual(len(cases), 12)
        case_ids = [case["case_id"] for case in cases]
        self.assertEqual(len(case_ids), len(set(case_ids)))

        with (REPOSITORY_ROOT / "data" / "public_set.jsonl").open(encoding="utf-8") as handle:
            public_targets = {
                json.loads(line)["ground_truth"]["parent_asin"]
                for line in handle
                if line.strip()
            }
        with (REPOSITORY_ROOT / "data" / "catalog.jsonl").open(encoding="utf-8") as handle:
            catalog_ids = {
                json.loads(line)["parent_asin"]
                for line in handle
                if line.strip()
            }
        for case in cases:
            self.assertTrue(case["messages"])
            self.assertIn(case["target_parent_asin"], catalog_ids)
            self.assertNotIn(case["target_parent_asin"], public_targets)
            score_from_turn = int(case.get("score_from_turn", 1))
            self.assertGreaterEqual(score_from_turn, 1)
            self.assertLessEqual(score_from_turn, len(case["messages"]))

    def test_default_fixture_is_resolved_from_module_location(self) -> None:
        self.assertTrue(DEFAULT_CASES.is_file())


if __name__ == "__main__":
    unittest.main()
