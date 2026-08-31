from __future__ import annotations

import unittest

from submission.src.contracts import ResponseGuard


class ResponseGuardTest(unittest.TestCase):
    def test_filters_invalid_duplicates_and_caps_top_ten(self) -> None:
        values = tuple(str(index) for index in range(12))
        guard = ResponseGuard(frozenset(values), lambda limit: values)

        result = guard.build(
            message="matches",
            ask_attribute="feature",
            recommendations=("bad", "1", "1", "2"),
            top_k=10,
        )

        ranked = [item["parent_asin"] for item in result["recommendations"]]
        self.assertEqual(len(ranked), 10)
        self.assertEqual(ranked[:2], ["1", "2"])
        self.assertEqual(len(ranked), len(set(ranked)))


if __name__ == "__main__":
    unittest.main()
