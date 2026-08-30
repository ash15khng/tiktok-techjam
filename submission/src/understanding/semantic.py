"""Optional JSON-validated interpretation via a Responses-compatible API."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from collections import OrderedDict
from dataclasses import replace
from threading import RLock
from time import perf_counter
from urllib.parse import urlparse

from submission.src.catalog.normalization import normalize_text, tokenize
from submission.src.config import AgentConfig
from submission.src.contracts import (
    ALLOWED_ATTRIBUTES,
    DisabledSemanticParser,
    SemanticInterpretation,
    SemanticParser,
    SemanticParserError,
    SemanticSlotHypothesis,
)
from submission.src.environment import load_runtime_environment


IMPLICIT_OUTCOME_RE = re.compile(
    r"\b(?:can(?:not|'t)|won't|wouldn't|makes?\s+my|feels?\s+like|reacts?\s+to|"
    r"enough\s+to|so\s+(?:that\s+)?i\s+can|after\s+(?:a\s+)?long|"
    r"because|for\s+someone\s+who)\b",
    re.IGNORECASE,
)
DETERMINISTIC_REPLY_RE = re.compile(
    r"\b(?:no\s+preference|use\s+your\s+judgment|not\s+quite\s+right|"
    r"what\s+matters\s+is|key\s+requirement\s+is|ignore\s+my\s+earlier)\b",
    re.IGNORECASE,
)
COMPLEX_CONNECTOR_RE = re.compile(
    r"\b(?:although|however|while|but|rather\s+than|something\s+for)\b",
    re.IGNORECASE,
)

# Provider response bounds are mirrored in both JSON schema and local
# validation. Raising them spends more tokens and permits more drift; lowering
# them may omit useful expansions. The current compact shape was exercised by
# mocked contract tests and live compatibility probes.
MAX_QUERY_REWRITES = 2
MAX_SUBJECTIVE_NEEDS = 3
MAX_SLOT_HYPOTHESES = 4
MAX_REWRITE_CHARS = 160
MAX_NEED_CHARS = 120
MAX_SLOT_VALUE_CHARS = 120
MAX_EVIDENCE_CHARS = 160
MAX_PROVIDER_SLOT_CONFIDENCE = 0.70
COMPLEX_MESSAGE_MIN_TERMS = 8
REQUIRED_SLOT_KEYS = frozenset({"attribute", "value", "confidence", "evidence"})
SEMANTIC_ATTRIBUTES = tuple(sorted(ALLOWED_ATTRIBUTES - {"other"}))
SEMANTIC_OPERATIONS = ("add", "replace", "exclude", "set_any")

# Direct GatedSemanticParser defaults support isolated tests. Production always
# supplies AgentConfig values. Raising the caps increases cost/memory; lowering
# them skips or evicts sooner.
DEFAULT_GATE_MAX_CALLS = 64
DEFAULT_GATE_CACHE_SIZE = 256
MAX_ENV_CALLS = 10_000
MIN_PROVIDER_TIMEOUT_SECONDS = 0.10
MAX_PROVIDER_TIMEOUT_SECONDS = 30.0
MILLISECONDS_PER_SECOND = 1_000

Transport = Callable[[urllib.request.Request, float], dict]

SEMANTIC_SCHEMA = {
    "type": "object",
    "properties": {
        "query_rewrites": {
            "type": "array",
            "items": {"type": "string", "maxLength": MAX_REWRITE_CHARS},
            "minItems": 0,
            "maxItems": MAX_QUERY_REWRITES,
        },
        "subjective_needs": {
            "type": "array",
            "items": {"type": "string", "maxLength": MAX_NEED_CHARS},
            "maxItems": MAX_SUBJECTIVE_NEEDS,
        },
        "slot_hypotheses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "attribute": {"type": "string", "enum": list(SEMANTIC_ATTRIBUTES)},
                    "operation": {"type": "string", "enum": list(SEMANTIC_OPERATIONS)},
                    "value": {"type": "string", "maxLength": MAX_SLOT_VALUE_CHARS},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "evidence": {"type": "string", "maxLength": MAX_EVIDENCE_CHARS},
                },
                "required": ["attribute", "operation", "value", "confidence", "evidence"],
                "additionalProperties": False,
            },
            "maxItems": MAX_SLOT_HYPOTHESES,
        },
    },
    "required": ["query_rewrites", "subjective_needs", "slot_hypotheses"],
    "additionalProperties": False,
}

SEMANTIC_TOOL_NAME = "submit_catalog_search_interpretation"

INSTRUCTIONS = """
You are the state interpreter for a conversational shopping search system.
Call submit_catalog_search_interpretation exactly once. The input contains the
previous active state and exactly one new customer message. Return at most two
standalone catalog-search rewrites, three subjective needs, and four slot
operations. Permitted fields are category, material, color, size, style, brand,
budget, feature, and use_case.

Slot operation semantics:
- add: retain existing values for this field and add the new value.
- replace: remove only earlier values of this same field, then add the new value.
- exclude: the customer rejects this value.
- set_any: the customer has no constraint for this field; value must be empty.

Preserve unrelated active constraints across turns. A correction to color must
not remove size, budget, use case, or category. Resolve pronouns and short clauses
using active state, but never invent evidence. Every operation needs confidence
from 0 to 1 and the shortest exact quote from the current customer message.

Each query rewrite must be a concrete, standalone product search query containing
the active product category when known and only currently active positive
constraints. It must not contain vague pronouns, cleared values, exclusions as
positive terms, product IDs, or unsupported brands/materials/colors/sizes/budgets.
A rewrite may translate an implied outcome into common catalog terminology and
may include a strongly entailed generic product noun:
- "cheap metal makes my ears itch" -> "hypoallergenic nickel free earrings"
- "wet and windy commute, not a heavy coat" -> "lightweight water resistant windbreaker"
- "fluffy at home, open toes, pillow padding" -> "fuzzy open toe memory foam house slippers"

The local program validates every field, operation, evidence span, length, and
catalog identifier boundary. When uncertain, omit the operation instead of
guessing. Local deterministic state remains the final authority on conflicts.
"""


def should_call_semantic_parser(message: str, *, has_fallback_span: bool = False) -> bool:
    """Cost gate based on parse gaps and language structure, not value lists."""

    if DETERMINISTIC_REPLY_RE.search(message):
        return False
    terms = tokenize(message, drop_stopwords=False)
    has_complex_connector = bool(COMPLEX_CONNECTOR_RE.search(message))
    return (
        has_fallback_span
        or bool(IMPLICIT_OUTCOME_RE.search(message))
        or (len(terms) >= COMPLEX_MESSAGE_MIN_TERMS and has_complex_connector)
    )


def _default_transport(request: urllib.request.Request, timeout: float) -> dict:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise SemanticParserError(f"semantic provider returned HTTP {error.code}") from None
    except (urllib.error.URLError, TimeoutError) as error:
        raise SemanticParserError(
            f"semantic provider unavailable: {type(error).__name__}"
        ) from None


class ResponsesSemanticParser:
    """Responses-compatible HTTP adapter with no third-party SDK.

    Input is a customer message plus compact active-state text. Output is a
    locally validated :class:`SemanticInterpretation`; credentials and raw
    provider bodies are never included in raised errors or diagnostics.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        max_input_chars: int,
        max_output_tokens: int,
        transport: Transport | None = None,
    ) -> None:
        if not api_key.strip() or not base_url.strip() or not model.strip():
            raise ValueError("api_key, base_url, and model are required")
        self._api_key = api_key
        self.responses_url = _responses_url(base_url)
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_input_chars = max_input_chars
        self.max_output_tokens = max_output_tokens
        self._transport = transport or _default_transport

    def interpret(self, message: str, context: str) -> SemanticInterpretation:
        bounded_context = str(context)[: self.max_input_chars // 2]
        try:
            active_state: object = json.loads(bounded_context) if bounded_context else {}
        except json.JSONDecodeError:
            active_state = {"legacy_summary": bounded_context}
        input_value = json.dumps(
            {
                "active_state": active_state,
                "customer_message": str(message)[: self.max_input_chars // 2],
            },
            ensure_ascii=False,
        )
        payload = {
            "model": self.model,
            "instructions": INSTRUCTIONS,
            "input": input_value,
            "stream": False,
            "max_output_tokens": self.max_output_tokens,
            "temperature": 0.0,
            "tools": [
                {
                    "type": "function",
                    "name": SEMANTIC_TOOL_NAME,
                    "description": (
                        "Return grounded catalog-search rewrites and optional "
                        "soft shopping hypotheses."
                    ),
                    "parameters": SEMANTIC_SCHEMA,
                    "strict": True,
                }
            ],
            "tool_choice": {"type": "function", "name": SEMANTIC_TOOL_NAME},
        }
        request = urllib.request.Request(
            self.responses_url,
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
        value: object | None = None
        for item in response.get("output", []):
            if not isinstance(item, dict) or item.get("type") != "function_call":
                continue
            if item.get("name") != SEMANTIC_TOOL_NAME:
                continue
            arguments = item.get("arguments")
            if isinstance(arguments, dict):
                value = arguments
            elif isinstance(arguments, str):
                try:
                    value = json.loads(arguments)
                except json.JSONDecodeError:
                    raise SemanticParserError(
                        "semantic function arguments were not valid JSON"
                    ) from None
            break

        output_text: str | None = None
        if value is None:
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
                raise SemanticParserError("semantic response contained no tool call or output text")
            try:
                value = json.loads(_strip_json_fence(output_text))
            except json.JSONDecodeError:
                raise SemanticParserError("semantic response was not valid JSON") from None
        if not isinstance(value, dict):
            raise SemanticParserError("semantic response root must be an object")

        rewrites = _validated_strings(
            value.get("query_rewrites"),
            limit=MAX_QUERY_REWRITES,
            max_length=MAX_REWRITE_CHARS,
        )
        needs = _validated_strings(
            value.get("subjective_needs"),
            limit=MAX_SUBJECTIVE_NEEDS,
            max_length=MAX_NEED_CHARS,
        )
        raw_hypotheses = value.get("slot_hypotheses")
        if not isinstance(raw_hypotheses, list):
            raw_hypotheses = []
        hypotheses: list[SemanticSlotHypothesis] = []
        for item in raw_hypotheses:
            if len(hypotheses) >= MAX_SLOT_HYPOTHESES:
                break
            if not isinstance(item, dict) or not REQUIRED_SLOT_KEYS.issubset(item):
                continue
            attribute = item["attribute"]
            operation = item.get("operation", "add")
            value_text = item["value"]
            evidence = item["evidence"]
            confidence = item["confidence"]
            if attribute not in ALLOWED_ATTRIBUTES:
                continue
            if operation not in SEMANTIC_OPERATIONS:
                continue
            if not isinstance(value_text, str):
                continue
            if operation == "set_any" and value_text.strip():
                continue
            if (
                operation != "set_any"
                and not value_text.strip()
                or len(value_text) > MAX_SLOT_VALUE_CHARS
            ):
                continue
            if (
                not isinstance(evidence, str)
                or not evidence.strip()
                or len(evidence) > MAX_EVIDENCE_CHARS
            ):
                continue
            if not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
                continue
            hypotheses.append(
                SemanticSlotHypothesis(
                    str(attribute),
                    value_text.strip(),
                    min(MAX_PROVIDER_SLOT_CONFIDENCE, float(confidence)),
                    evidence.strip(),
                    str(operation),
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
    """Cost gate, bounded cache, call budget, and reliable provider fallback."""

    def __init__(
        self,
        provider: SemanticParser,
        *,
        max_calls: int = DEFAULT_GATE_MAX_CALLS,
        cache_size: int = DEFAULT_GATE_CACHE_SIZE,
    ) -> None:
        self.provider = provider
        self.max_calls = max(0, int(max_calls))
        self.cache_size = max(0, int(cache_size))
        self._cache: OrderedDict[tuple[str, str], SemanticInterpretation] = OrderedDict()
        self._lock = RLock()
        self._metrics = {
            "gate_skips": 0,
            "provider_calls": 0,
            "successful_calls": 0,
            "failed_calls": 0,
            "cache_hits": 0,
            "budget_skips": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "provider_latency_ms": 0.0,
        }

    def interpret(self, message: str, context: str) -> SemanticInterpretation:
        if not should_call_semantic_parser(message):
            with self._lock:
                self._metrics["gate_skips"] += 1
            return SemanticInterpretation()
        return self.interpret_eligible(message, context)

    def interpret_eligible(self, message: str, context: str) -> SemanticInterpretation:
        """Apply budget/cache/fallback after an external policy justifies a call."""

        key = (normalize_text(message), normalize_text(context))
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                self._metrics["cache_hits"] += 1
                return replace(cached, prompt_tokens=0, completion_tokens=0)
            if self._metrics["provider_calls"] >= self.max_calls:
                self._metrics["budget_skips"] += 1
                return SemanticInterpretation()
            self._metrics["provider_calls"] += 1
        started = perf_counter()
        try:
            result = self.provider.interpret(message, context)
        except (SemanticParserError, OSError, ValueError, TypeError):
            with self._lock:
                self._metrics["failed_calls"] += 1
                self._metrics["provider_latency_ms"] += (
                    perf_counter() - started
                ) * MILLISECONDS_PER_SECOND
            return SemanticInterpretation()
        with self._lock:
            self._metrics["successful_calls"] += 1
            self._metrics["prompt_tokens"] += result.prompt_tokens
            self._metrics["completion_tokens"] += result.completion_tokens
            self._metrics["provider_latency_ms"] += (
                perf_counter() - started
            ) * MILLISECONDS_PER_SECOND
            if self.cache_size:
                self._cache[key] = result
                self._cache.move_to_end(key)
                while len(self._cache) > self.cache_size:
                    self._cache.popitem(last=False)
        return result

    def stats(self) -> dict[str, int | float]:
        """Return credential-free diagnostics for evaluation and disclosure."""

        with self._lock:
            return dict(self._metrics)


def semantic_parser_from_environment(config: AgentConfig) -> SemanticParser:
    provider = configured_responses_parser_from_environment(config)
    if provider is None:
        return DisabledSemanticParser()
    return GatedSemanticParser(
        provider,
        max_calls=_environment_max_calls(config.semantic_max_calls_per_run),
        cache_size=config.semantic_cache_size,
    )


def configured_responses_parser_from_environment(
    config: AgentConfig,
) -> ResponsesSemanticParser | None:
    """Build an ungated provider for diagnostics, or return ``None`` safely."""

    load_runtime_environment()
    if os.environ.get("SHOPPING_COPILOT_LLM_ENABLED", "").casefold() not in {"1", "true", "yes"}:
        return None
    api_key = os.environ.get("SOCLAAS_API_KEY", "").strip()
    base_url = os.environ.get("SOCLAAS_BASE_URL", "").strip()
    model = os.environ.get("SHOPPING_COPILOT_LLM_MODEL", "").strip()
    if not api_key or not base_url or not model:
        return None
    try:
        return ResponsesSemanticParser(
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout_seconds=_environment_timeout(config.semantic_timeout_seconds),
            max_input_chars=config.semantic_max_input_chars,
            max_output_tokens=config.semantic_max_output_tokens,
        )
    except ValueError:
        return None


# Compatibility alias for collaborators importing the earlier adapter name.
OpenAIResponsesSemanticParser = ResponsesSemanticParser


def _responses_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base_url must be an absolute HTTP(S) URL")
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("remote base_url must use HTTPS")
    if parsed.path.rstrip("/").endswith("/responses"):
        return normalized
    return f"{normalized}/responses"


def _strip_json_fence(value: str) -> str:
    cleaned = value.strip()
    if not cleaned.startswith("```"):
        return cleaned
    lines = cleaned.splitlines()
    if len(lines) < 3 or lines[-1].strip() != "```":
        return cleaned
    if lines[0].strip().casefold() not in {"```", "```json"}:
        return cleaned
    return "\n".join(lines[1:-1]).strip()


def _environment_max_calls(default: int) -> int:
    raw = os.environ.get("SHOPPING_COPILOT_LLM_MAX_CALLS", "").strip()
    if not raw:
        return max(0, int(default))
    try:
        return min(MAX_ENV_CALLS, max(0, int(raw)))
    except ValueError:
        return max(0, int(default))


def _environment_timeout(default: float) -> float:
    raw = os.environ.get("SHOPPING_COPILOT_LLM_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return min(
            MAX_PROVIDER_TIMEOUT_SECONDS,
            max(MIN_PROVIDER_TIMEOUT_SECONDS, float(default)),
        )
    try:
        return min(
            MAX_PROVIDER_TIMEOUT_SECONDS,
            max(MIN_PROVIDER_TIMEOUT_SECONDS, float(raw)),
        )
    except ValueError:
        return min(
            MAX_PROVIDER_TIMEOUT_SECONDS,
            max(MIN_PROVIDER_TIMEOUT_SECONDS, float(default)),
        )


def _validated_strings(value: object, *, limit: int, max_length: int) -> tuple[str, ...]:
    if isinstance(value, str):
        candidates = [value]
    elif isinstance(value, list):
        candidates = value
    else:
        return ()
    result: list[str] = []
    for item in candidates:
        if len(result) >= limit:
            break
        if not isinstance(item, str) or not item.strip() or len(item) > max_length:
            continue
        cleaned = item.strip()
        if cleaned not in result:
            result.append(cleaned)
    return tuple(result)


def _nonnegative_int(value: object) -> int:
    return int(value) if isinstance(value, int) and value >= 0 else 0
