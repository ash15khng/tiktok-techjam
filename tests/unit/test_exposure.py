from __future__ import annotations

import unittest

from shopping_copilot.ranking.exposure import unseen_first
from shopping_copilot.retrieval.models import CandidateEvidence


class RecommendationExposureTest(unittest.TestCase):
    def test_unseen_candidates_precede_previously_shown_candidates(self) -> None:
        candidates = [
            CandidateEvidence("A", final_score=3.0),
            CandidateEvidence("B", final_score=2.0),
            CandidateEvidence("C", final_score=1.0),
        ]

        result = unseen_first(candidates, {"A"})

        self.assertEqual([item.parent_asin for item in result], ["B", "C", "A"])

    def test_order_is_stable_inside_each_partition(self) -> None:
        candidates = [CandidateEvidence(value) for value in ("A", "B", "C", "D")]

        result = unseen_first(candidates, {"A", "C"})

        self.assertEqual([item.parent_asin for item in result], ["B", "D", "A", "C"])


if __name__ == "__main__":
    unittest.main()
