"""Stable interfaces at the Agent and optional-model boundaries."""

from __future__ import annotations

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
