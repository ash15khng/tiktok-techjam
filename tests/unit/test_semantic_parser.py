from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from submission.src.config import AgentConfig
from submission.src.contracts import DisabledSemanticParser, SemanticInterpretation, SemanticParserError
from submission.src.understanding.semantic import (
    GatedSemanticParser,
    ResponsesSemanticParser,
    SEMANTIC_TOOL_NAME,
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


def completed_tool_response(payload: dict) -> dict:
    return {
        "status": "completed",
        "output": [
            {
                "type": "function_call",
                "name": SEMANTIC_TOOL_NAME,
                "arguments": json.dumps(payload),
                "status": "completed",
            }
        ],
        "usage": {"input_tokens": 41, "output_tokens": 17},
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

        parser = ResponsesSemanticParser(
            api_key="test-secret",
            base_url="https://gateway.example/v1",
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
        self.assertEqual(observed["url"], "https://gateway.example/v1/responses")
        self.assertEqual(observed["authorization"], "Bearer test-secret")
        self.assertEqual(observed["timeout"], 3.5)
        self.assertEqual(
            set(observed["body"]),
            {
                "model",
                "instructions",
                "input",
                "stream",
                "max_output_tokens",
                "temperature",
                "tools",
                "tool_choice",
            },
        )
        self.assertFalse(observed["body"]["stream"])
        self.assertEqual(observed["body"]["temperature"], 0.0)
        self.assertIn("strongly entailed generic product noun", observed["body"]["instructions"])
        self.assertEqual(observed["body"]["tool_choice"]["name"], SEMANTIC_TOOL_NAME)
        self.assertTrue(observed["body"]["tools"][0]["strict"])
        self.assertEqual(observed["body"]["tools"][0]["parameters"]["properties"]["query_rewrites"]["minItems"], 1)
        self.assertIsInstance(observed["body"]["input"], str)
        self.assertNotIn("test-secret", json.dumps(observed["body"]))

    def test_malformed_response_raises_safe_provider_error(self) -> None:
        parser = ResponsesSemanticParser(
            api_key="secret",
            base_url="https://gateway.example/v1/responses",
            model="model",
            timeout_seconds=1,
            max_input_chars=100,
            max_output_tokens=100,
            transport=lambda request, timeout: {"status": "completed", "output": []},
        )

        with self.assertRaisesRegex(SemanticParserError, "no tool call or output text"):
            parser.interpret("subjective request", "")

    def test_function_call_arguments_are_preferred_and_validated(self) -> None:
        parser = ResponsesSemanticParser(
            api_key="secret",
            base_url="https://gateway.example/v1",
            model="model",
            timeout_seconds=1,
            max_input_chars=100,
            max_output_tokens=100,
            transport=lambda request, timeout: completed_tool_response(
                {
                    "query_rewrites": ["lightweight water resistant windbreaker"],
                    "subjective_needs": ["easy to pack"],
                    "slot_hypotheses": [],
                }
            ),
        )

        result = parser.interpret("wet and windy commute", "")

        self.assertEqual(result.query_rewrites, ("lightweight water resistant windbreaker",))
        self.assertEqual(result.prompt_tokens, 41)
        self.assertEqual(result.completion_tokens, 17)

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

    def test_gate_caches_success_without_double_reporting_tokens_and_enforces_budget(self) -> None:
        class CountingProvider:
            calls = 0

            def interpret(self, message: str, context: str) -> SemanticInterpretation:
                self.calls += 1
                return SemanticInterpretation(query_rewrites=("cushioned shoes",), prompt_tokens=11, completion_tokens=7)

        provider = CountingProvider()
        parser = GatedSemanticParser(provider, max_calls=1, cache_size=2)

        first = parser.interpret("shoes that feel like walking on pillows", "category=shoes")
        cached = parser.interpret("shoes that feel like walking on pillows", "category=shoes")
        budgeted = parser.interpret("shoes for someone who stands all day", "category=shoes")

        self.assertEqual(provider.calls, 1)
        self.assertEqual(first.prompt_tokens, 11)
        self.assertEqual(cached.query_rewrites, first.query_rewrites)
        self.assertEqual(cached.prompt_tokens, 0)
        self.assertEqual(budgeted, SemanticInterpretation())
        self.assertEqual(parser.stats()["cache_hits"], 1)
        self.assertEqual(parser.stats()["budget_skips"], 1)
        self.assertEqual(parser.stats()["prompt_tokens"], 11)

    def test_policy_approved_call_bypasses_language_gate_but_keeps_budget(self) -> None:
        class CountingProvider:
            calls = 0

            def interpret(self, message: str, context: str) -> SemanticInterpretation:
                self.calls += 1
                return SemanticInterpretation(query_rewrites=("navy shirt",))

        provider = CountingProvider()
        parser = GatedSemanticParser(provider, max_calls=1)

        result = parser.interpret_eligible("navy", "category=shirt")
        budgeted = parser.interpret_eligible("red", "category=shirt")

        self.assertEqual(result.query_rewrites, ("navy shirt",))
        self.assertEqual(budgeted, SemanticInterpretation())
        self.assertEqual(provider.calls, 1)
        self.assertEqual(parser.stats()["budget_skips"], 1)

    def test_single_json_code_fence_is_tolerated(self) -> None:
        payload = {
            "query_rewrites": [],
            "subjective_needs": ["comfortable"],
            "slot_hypotheses": [],
        }
        response = completed_response(payload)
        response["output"][1]["content"][0]["text"] = f"```json\n{json.dumps(payload)}\n```"
        parser = ResponsesSemanticParser(
            api_key="secret",
            base_url="https://gateway.example/v1",
            model="model",
            timeout_seconds=1,
            max_input_chars=100,
            max_output_tokens=100,
            transport=lambda request, timeout: response,
        )

        result = parser.interpret("comfortable everyday shoes", "category=shoes")

        self.assertEqual(result.subjective_needs, ("comfortable",))

    def test_small_model_shape_deviations_are_safely_bounded(self) -> None:
        response = completed_response(
            {
                "query_rewrites": ["one", "two", "three"],
                "subjective_needs": "comfortable",
                "slot_hypotheses": [
                    {"attribute": "feature", "value": "soft", "confidence": 0.8, "evidence": "comfortable"},
                    {"attribute": "not_allowed", "value": "bad", "confidence": 1, "evidence": "comfortable"},
                ],
            }
        )
        parser = ResponsesSemanticParser(
            api_key="secret",
            base_url="https://gateway.example/v1",
            model="model",
            timeout_seconds=1,
            max_input_chars=100,
            max_output_tokens=100,
            transport=lambda request, timeout: response,
        )

        result = parser.interpret("comfortable shoes", "")

        self.assertEqual(result.query_rewrites, ("one", "two"))
        self.assertEqual(result.subjective_needs, ("comfortable",))
        self.assertEqual(len(result.slot_hypotheses), 1)

    def test_environment_factory_is_disabled_without_complete_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = str(Path(directory) / "missing.env")
            with patch.dict(
                os.environ,
                {
                    "SHOPPING_COPILOT_ENV_FILE": missing,
                    "SHOPPING_COPILOT_LLM_ENABLED": "1",
                },
                clear=True,
            ):
                parser = semantic_parser_from_environment(AgentConfig())

        self.assertIsInstance(parser, DisabledSemanticParser)

    def test_environment_factory_uses_soclaas_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = str(Path(directory) / "missing.env")
            with patch.dict(
                os.environ,
                {
                    "SHOPPING_COPILOT_ENV_FILE": missing,
                    "SHOPPING_COPILOT_LLM_ENABLED": "1",
                    "SHOPPING_COPILOT_LLM_MAX_CALLS": "3",
                    "SHOPPING_COPILOT_LLM_MODEL": "llama3.1:8b",
                    "SHOPPING_COPILOT_LLM_TIMEOUT_SECONDS": "7.5",
                    "SOCLAAS_BASE_URL": "https://gateway.example/v1",
                    "SOCLAAS_API_KEY": "secret",
                },
                clear=True,
            ):
                parser = semantic_parser_from_environment(AgentConfig())

        self.assertIsInstance(parser, GatedSemanticParser)
        self.assertEqual(parser.provider.responses_url, "https://gateway.example/v1/responses")
        self.assertEqual(parser.provider.timeout_seconds, 7.5)
        self.assertEqual(parser.max_calls, 3)

    def test_remote_plain_http_endpoint_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            ResponsesSemanticParser(
                api_key="secret",
                base_url="http://gateway.example/v1",
                model="model",
                timeout_seconds=1,
                max_input_chars=100,
                max_output_tokens=100,
            )

    def test_semantic_gate_targets_subjective_language(self) -> None:
        self.assertTrue(
            should_call_semantic_parser(
                "I need something polished but comfortable for a humid outdoor wedding."
            )
        )
        self.assertFalse(should_call_semantic_parser("I don't have a preference for color."))


if __name__ == "__main__":
    unittest.main()
