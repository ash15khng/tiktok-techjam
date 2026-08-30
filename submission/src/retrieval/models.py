"""Retrieval request, plan, and candidate evidence models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RetrievalPlan:
    focus_score: float
    generator_weights: dict[str, float]
    generator_limit: int


@dataclass
class CandidateEvidence:
    parent_asin: str
    generator_ranks: dict[str, int] = field(default_factory=dict)
    raw_scores: dict[str, float] = field(default_factory=dict)
    rrf_score: float = 0.0
    final_score: float = 0.0


@dataclass(frozen=True)
class RetrievalAssessment:
    candidate_count: int
    generator_agreement: float
    top10_stability: float
