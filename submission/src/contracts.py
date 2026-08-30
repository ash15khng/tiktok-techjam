"""Stable interfaces at the Agent and optional-model boundaries."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol


ALLOWED_ATTRIBUTES = frozenset(
    {
        "category",
        "material",
        "color",
        "size",
        "style",
        "brand",
        "budget",
        "feature",
        "use_case",
        "other",
    }
)
CONTRACT_MAX_RECOMMENDATIONS = 10


@dataclass(frozen=True)
class SemanticSlotHypothesis:
    """Soft model proposal that still requires deterministic grounding."""

    attribute: str
    value: str
    confidence: float
    evidence: str


@dataclass(frozen=True)
class SemanticInterpretation:
    """Validated, optional semantic hints; never a source of catalog IDs."""

    query_rewrites: tuple[str, ...] = ()
    subjective_needs: tuple[str, ...] = ()
    slot_hypotheses: tuple[SemanticSlotHypothesis, ...] = ()
    prompt_tokens: int = 0
    completion_tokens: int = 0


class SemanticParser(Protocol):
    """Provider boundary for a local model or legally accessible LLM API."""

    def interpret(self, message: str, context: str) -> SemanticInterpretation:
        """Return structured hints or raise a provider-specific error."""


class DisabledSemanticParser:
    """Offline default used until a semantic provider can be evaluated."""

    def interpret(self, message: str, context: str) -> SemanticInterpretation:
        return SemanticInterpretation()


class SemanticParserError(RuntimeError):
    """Safe provider-boundary failure without credentials or response bodies."""


class ResponseGuard:
    """Build a contract-safe response from untrusted component output.

    Input recommendations may contain duplicates or invalid IDs. Output always
    contains unique frozen-catalog IDs in first-seen order and includes valid,
    non-negative token accounting.
    """

    def __init__(
        self,
        valid_ids: frozenset[str],
        fallback: Callable[[int], Iterable[str]],
    ) -> None:
        self._valid_ids = valid_ids
        self._fallback = fallback

    def build(
        self,
        *,
        message: str,
        ask_attribute: str | None,
        recommendations: Iterable[str],
        top_k: int,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> dict:
        limit = max(0, min(int(top_k), CONTRACT_MAX_RECOMMENDATIONS))
        attribute = ask_attribute if ask_attribute in ALLOWED_ATTRIBUTES else None
        ranked: list[str] = []
        seen: set[str] = set()
        for candidate in recommendations:
            parent_asin = str(candidate).strip()
            if parent_asin in self._valid_ids and parent_asin not in seen:
                seen.add(parent_asin)
                ranked.append(parent_asin)
            if len(ranked) >= limit:
                break
        if len(ranked) < limit:
            for candidate in self._fallback(limit):
                parent_asin = str(candidate).strip()
                if parent_asin in self._valid_ids and parent_asin not in seen:
                    seen.add(parent_asin)
                    ranked.append(parent_asin)
                if len(ranked) >= limit:
                    break
        return {
            "message": str(message or "Here are the closest catalog matches."),
            "ask_attribute": attribute,
            "recommendations": [{"parent_asin": value} for value in ranked],
            "usage": {
                "prompt_tokens": max(0, int(prompt_tokens)),
                "completion_tokens": max(0, int(completion_tokens)),
            },
        }
