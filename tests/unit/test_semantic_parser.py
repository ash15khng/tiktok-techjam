from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from shopping_copilot.config import MVPConfig
from shopping_copilot.contracts import DisabledSemanticParser, SemanticInterpretation, SemanticParserError
from shopping_copilot.understanding.semantic import (
    GatedSemanticParser,
    OpenAIResponsesSemanticParser,
    semantic_parser_from_environment,
    should_call_semantic_parser,
)


def completed_response(payload: dict) -> dict:
    return {
        "status": "completed",
        "output": [
            {"type": "reasoning"},
            {
                "type": "message",
                "content": [{"type": "output_text", "text": json.dumps(payload)}],
            },
        ],
        "usage": {"input_tokens": 37, "output_tokens": 19},
    }


class SemanticParserTest(unittest.TestCase):
    def test_structured_response_is_validated_and_token_usage_is_kept(self) -> None:
        observed = {}

        def transport(request, timeout):
            observed["url"] = request.full_url
            observed["authorization"] = request.headers["Authorization"]
            observed["body"] = json.loads(request.data.decode("utf-8"))
            observed["timeout"] = timeout
            return completed_response(
                {
                    "query_rewrites": ["breathable formal wedding shoes"],
                    "subjective_needs": ["comfortable in humid weather"],
                    "slot_hypotheses": [
                        {
                            "attribute": "use_case",
                            "value": "outdoor wedding",
                            "confidence": 0.91,
                            "evidence": "humid outdoor wedding",
                        }
                    ],
                }
            )

        parser = OpenAIResponsesSemanticParser(
            api_key="test-secret",
            model="explicit-test-model",
            timeout_seconds=3.5,
            max_input_chars=4000,
            max_output_tokens=500,
            transport=transport,
        )

        result = parser.interpret(
            "I need something polished but comfortable for a humid outdoor wedding.",
            "category=shoes",
        )

        self.assertEqual(result.query_rewrites, ("breathable formal wedding shoes",))
        self.assertEqual(result.prompt_tokens, 37)
        self.assertEqual(result.completion_tokens, 19)
        self.assertEqual(result.slot_hypotheses[0].confidence, 0.70)
        self.assertEqual(observed["url"], "https://api.openai.com/v1/responses")
        self.assertEqual(observed["authorization"], "Bearer test-secret")
        self.assertEqual(observed["timeout"], 3.5)
        self.assertFalse(observed["body"]["store"])
        self.assertTrue(observed["body"]["text"]["format"]["strict"])
        self.assertNotIn("test-secret", json.dumps(observed["body"]))

    def test_malformed_response_raises_safe_provider_error(self) -> None:
        parser = OpenAIResponsesSemanticParser(
            api_key="secret",
            model="model",
            timeout_seconds=1,
            max_input_chars=100,
            max_output_tokens=100,
            transport=lambda request, timeout: {"status": "completed", "output": []},
        )

        with self.assertRaisesRegex(SemanticParserError, "no output text"):
            parser.interpret("subjective request", "")

    def test_gate_skips_simple_reply_and_falls_back_on_failure(self) -> None:
        class FailingProvider:
            calls = 0

            def interpret(self, message: str, context: str) -> SemanticInterpretation:
                self.calls += 1
                raise SemanticParserError("simulated")

        provider = FailingProvider()
        parser = GatedSemanticParser(provider)

        simple = parser.interpret("navy", "")
        complex_result = parser.interpret(
            "I need something polished but comfortable for a humid outdoor wedding.",
            "",
        )

        self.assertEqual(simple, SemanticInterpretation())
        self.assertEqual(complex_result, SemanticInterpretation())
        self.assertEqual(provider.calls, 1)

    def test_environment_factory_is_disabled_without_complete_opt_in(self) -> None:
        with patch.dict(os.environ, {"SHOPPING_COPILOT_LLM_ENABLED": "1"}, clear=True):
            parser = semantic_parser_from_environment(MVPConfig())

        self.assertIsInstance(parser, DisabledSemanticParser)

    def test_semantic_gate_targets_subjective_language(self) -> None:
        self.assertTrue(
            should_call_semantic_parser(
                "I need something polished but comfortable for a humid outdoor wedding."
            )
        )
        self.assertFalse(should_call_semantic_parser("I don't have a preference for color."))


if __name__ == "__main__":
    unittest.main()
