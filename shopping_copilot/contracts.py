"""Stable interfaces at the Agent and optional-model boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable, Iterable
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


@dataclass(frozen=True)
class SemanticInterpretation:
    """Validated, optional semantic hints; never a source of catalog IDs."""

    query_rewrites: tuple[str, ...] = ()
    subjective_needs: tuple[str, ...] = ()
    prompt_tokens: int = 0
    completion_tokens: int = 0


class SemanticParser(Protocol):
    """Provider boundary for a future local model or legal LLM API."""

    def interpret(self, message: str, context: str) -> SemanticInterpretation:
        """Return structured hints or raise a provider-specific error."""


class DisabledSemanticParser:
    """Offline default used until a semantic provider can be evaluated."""

    def interpret(self, message: str, context: str) -> SemanticInterpretation:
        return SemanticInterpretation()


class ResponseGuard:
    """Build a contract-safe response from untrusted component output."""

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
        limit = max(0, min(int(top_k), 10))
        attribute = ask_attribute if ask_attribute in ALLOWED_ATTRIBUTES else None
        ranked: list[str] = []
        seen: set[str] = set()
        for candidate in (*recommendations, *self._fallback(limit)):
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
