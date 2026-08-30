from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping, Sequence

from shopping_copilot.dialog.models import ActiveConstraint, ActiveState
from shopping_copilot.understanding.models import Attribute


@dataclass(frozen=True)
class RetrievalRequest:
    """Encapsulates the structured query context for multi-generator retrieval."""
    category: str | None
    active_constraints: tuple[ActiveConstraint, ...]
    exclusions: tuple[ActiveConstraint, ...]
    product_terms: tuple[str, ...]
    residual_terms: tuple[str, ...]
    raw_phrases: tuple[str, ...]
    profile_preferences: tuple[str, ...]
    turns_remaining: int

    @classmethod
    def from_active_state(cls, state: ActiveState, turns_remaining: int = 10) -> RetrievalRequest:
        return cls(
            category=state.category,
            active_constraints=state.constraints,
            exclusions=state.exclusions,
            product_terms=state.residual_product_terms,
            residual_terms=state.residual_product_terms,
            raw_phrases=state.raw_phrases,
            profile_preferences=state.profile_preferences,
            turns_remaining=turns_remaining,
        )


@dataclass(frozen=True)
class RetrievalPlan:
    """Configured generator weights and candidate depth limits for a retrieval turn."""
    focus_score: float
    generator_weights: Mapping[str, float]
    generator_limits: Mapping[str, int]
    reason_codes: tuple[str, ...] = ()


@dataclass
class CandidateEvidence:
    """Tracks candidate rank and signal evidence across multiple generators."""
    parent_asin: str
    generator_ranks: dict[str, int] = field(default_factory=dict)
    raw_scores: dict[str, float] = field(default_factory=dict)
    matched_fields: set[str] = field(default_factory=set)
    constraint_results: dict[str, Literal["match", "contradiction", "unknown"]] = field(default_factory=dict)
    rrf_score: float = 0.0
    lightweight_score: float = 0.0
    final_score: float = 0.0
    reason_codes: list[str] = field(default_factory=list)

