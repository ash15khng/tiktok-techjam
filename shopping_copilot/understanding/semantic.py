"""Optional schema-constrained semantic interpretation via the Responses API."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable

from shopping_copilot.catalog.normalization import tokenize
from shopping_copilot.config import MVPConfig
from shopping_copilot.contracts import (
    ALLOWED_ATTRIBUTES,
    DisabledSemanticParser,
    SemanticInterpretation,
    SemanticParser,
    SemanticParserError,
    SemanticSlotHypothesis,
)


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
SUBJECTIVE_LANGUAGE_RE = re.compile(
    r"\b(?:comfortable|comfort|polished|professional|versatile|stylish|subtle|"
    r"bold|durable|lightweight|breathable|premium|minimal|modest|formal|casual|"
    r"gift|occasion|commute|travel|humid|rainy|warm|cold|everyday)\b",
    re.IGNORECASE,
)
DETERMINISTIC_REPLY_RE = re.compile(
    r"\b(?:no\s+preference|use\s+your\s+judgment|not\s+quite\s+right|"
    r"what\s+matters\s+is|key\s+requirement\s+is|ignore\s+my\s+earlier)\b",
    re.IGNORECASE,
)

Transport = Callable[[urllib.request.Request, float], dict]

SEMANTIC_SCHEMA = {
    "type": "object",
    "properties": {
        "query_rewrites": {
            "type": "array",
            "items": {"type": "string", "maxLength": 160},
            "maxItems": 3,
        },
        "subjective_needs": {
            "type": "array",
            "items": {"type": "string", "maxLength": 120},
            "maxItems": 5,
        },
        "slot_hypotheses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "attribute": {"type": "string", "enum": sorted(ALLOWED_ATTRIBUTES)},
                    "value": {"type": "string", "maxLength": 120},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "evidence": {"type": "string", "maxLength": 160},
                },
                "required": ["attribute", "value", "confidence", "evidence"],
                "additionalProperties": False,
            },
            "maxItems": 8,
        },
    },
    "required": ["query_rewrites", "subjective_needs", "slot_hypotheses"],
    "additionalProperties": False,
}

INSTRUCTIONS = """You interpret customer language for catalog search.
Return only the requested structured output. Never generate product IDs.
Keep rewrites short and catalog-searchable. Preserve the customer's meaning,
negation, alternatives, and uncertainty. Do not invent brands, materials,
budgets, sizes, or preferences. Slot hypotheses are soft proposals supported by
an exact evidence span; deterministic rules and catalog grounding remain final.
"""


def should_call_semantic_parser(message: str) -> bool:
    """Cost gate for language the deterministic rules are least suited to."""

    if DETERMINISTIC_REPLY_RE.search(message):
        return False
    terms = tokenize(message, drop_stopwords=False)
    has_complex_connector = bool(re.search(r"\b(?:although|however|while|but|something\s+for)\b", message, re.I))
    return bool(SUBJECTIVE_LANGUAGE_RE.search(message)) or (len(terms) >= 16 and has_complex_connector)


def _default_transport(request: urllib.request.Request, timeout: float) -> dict:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise SemanticParserError(f"semantic provider returned HTTP {error.code}") from None
    except (urllib.error.URLError, TimeoutError) as error:
        raise SemanticParserError(f"semantic provider unavailable: {type(error).__name__}") from None


class OpenAIResponsesSemanticParser:
    """Small HTTP adapter so the reliable path has no SDK dependency."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        max_input_chars: int,
        max_output_tokens: int,
        transport: Transport | None = None,
    ) -> None:
        if not api_key.strip() or not model.strip():
            raise ValueError("api_key and model are required")
        self._api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_input_chars = max_input_chars
        self.max_output_tokens = max_output_tokens
        self._transport = transport or _default_transport

    def interpret(self, message: str, context: str) -> SemanticInterpretation:
        input_value = json.dumps(
            {
                "active_context": str(context)[: self.max_input_chars // 2],
                "customer_message": str(message)[: self.max_input_chars // 2],
            },
            ensure_ascii=False,
        )
        payload = {
            "model": self.model,
            "instructions": INSTRUCTIONS,
            "input": [{"role": "user", "content": [{"type": "input_text", "text": input_value}]}],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "shopping_intent",
                    "strict": True,
                    "schema": SEMANTIC_SCHEMA,
                }
            },
            "max_output_tokens": self.max_output_tokens,
            "store": False,
        }
        request = urllib.request.Request(
            OPENAI_RESPONSES_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        response = self._transport(request, self.timeout_seconds)
        return self._parse_response(response)

    @staticmethod
    def _parse_response(response: dict) -> SemanticInterpretation:
        if response.get("status") != "completed":
            raise SemanticParserError("semantic response did not complete")
        output_text: str | None = None
        for item in response.get("output", []):
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if isinstance(content, dict) and content.get("type") == "output_text":
                    output_text = content.get("text")
                    break
            if output_text is not None:
                break
        if not isinstance(output_text, str):
            raise SemanticParserError("semantic response contained no output text")
        try:
            value = json.loads(output_text)
        except json.JSONDecodeError:
            raise SemanticParserError("semantic response was not valid JSON") from None
        if not isinstance(value, dict):
            raise SemanticParserError("semantic response root must be an object")

        rewrites = _validated_strings(value.get("query_rewrites"), limit=3, max_length=160)
        needs = _validated_strings(value.get("subjective_needs"), limit=5, max_length=120)
        raw_hypotheses = value.get("slot_hypotheses")
        if not isinstance(raw_hypotheses, list) or len(raw_hypotheses) > 8:
            raise SemanticParserError("invalid slot_hypotheses")
        hypotheses: list[SemanticSlotHypothesis] = []
        for item in raw_hypotheses:
            if not isinstance(item, dict) or set(item) != {"attribute", "value", "confidence", "evidence"}:
                raise SemanticParserError("invalid slot hypothesis")
            attribute = item["attribute"]
            value_text = item["value"]
            evidence = item["evidence"]
            confidence = item["confidence"]
            if attribute not in ALLOWED_ATTRIBUTES:
                raise SemanticParserError("invalid semantic attribute")
            if not isinstance(value_text, str) or not value_text.strip() or len(value_text) > 120:
                raise SemanticParserError("invalid semantic value")
            if not isinstance(evidence, str) or not evidence.strip() or len(evidence) > 160:
                raise SemanticParserError("invalid semantic evidence")
            if not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
                raise SemanticParserError("invalid semantic confidence")
            hypotheses.append(
                SemanticSlotHypothesis(
                    str(attribute),
                    value_text.strip(),
                    min(0.70, float(confidence)),
                    evidence.strip(),
                )
            )
        usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
        return SemanticInterpretation(
            query_rewrites=rewrites,
            subjective_needs=needs,
            slot_hypotheses=tuple(hypotheses),
            prompt_tokens=_nonnegative_int(usage.get("input_tokens")),
            completion_tokens=_nonnegative_int(usage.get("output_tokens")),
        )


class GatedSemanticParser:
    """Skip simple turns and convert provider failures into a safe no-op."""

    def __init__(self, provider: SemanticParser) -> None:
        self.provider = provider

    def interpret(self, message: str, context: str) -> SemanticInterpretation:
        if not should_call_semantic_parser(message):
            return SemanticInterpretation()
        try:
            return self.provider.interpret(message, context)
        except (SemanticParserError, OSError, ValueError, TypeError):
            return SemanticInterpretation()


def semantic_parser_from_environment(config: MVPConfig) -> SemanticParser:
    if os.environ.get("SHOPPING_COPILOT_LLM_ENABLED", "").casefold() not in {"1", "true", "yes"}:
        return DisabledSemanticParser()
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    model = os.environ.get("SHOPPING_COPILOT_LLM_MODEL", "").strip()
    if not api_key or not model:
        return DisabledSemanticParser()
    return GatedSemanticParser(
        OpenAIResponsesSemanticParser(
            api_key=api_key,
            model=model,
            timeout_seconds=config.semantic_timeout_seconds,
            max_input_chars=config.semantic_max_input_chars,
            max_output_tokens=config.semantic_max_output_tokens,
        )
    )


def _validated_strings(value: object, *, limit: int, max_length: int) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > limit:
        raise SemanticParserError("invalid semantic string list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip() or len(item) > max_length:
            raise SemanticParserError("invalid semantic string")
        cleaned = item.strip()
        if cleaned not in result:
            result.append(cleaned)
    return tuple(result)


def _nonnegative_int(value: object) -> int:
    return int(value) if isinstance(value, int) and value >= 0 else 0
