from __future__ import annotations

import unittest

from submission.src.config import AgentConfig
from submission.src.contracts import DisabledSemanticParser


class ContractDefaultsTest(unittest.TestCase):
    def test_defaults_respect_agent_limits(self) -> None:
        config = AgentConfig()

        self.assertEqual(config.max_recommendations, 10)
        self.assertGreaterEqual(config.candidate_depth, config.max_recommendations)

    def test_disabled_semantic_parser_is_a_safe_noop(self) -> None:
        result = DisabledSemanticParser().interpret("red running shoes", "")

        self.assertEqual(result.query_rewrites, ())
        self.assertEqual(result.prompt_tokens + result.completion_tokens, 0)


if __name__ == "__main__":
    unittest.main()
