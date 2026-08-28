"""Runtime configuration shared by the deterministic MVP components."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MVPConfig:
    """Small, explicit set of MVP controls.

    Values are initial engineering guesses. They must be tuned with controlled
    public-set experiments rather than treated as learned probabilities.
    """

    candidate_depth: int = 200
    rrf_k: int = 60
    max_query_terms: int = 40
    max_recommendations: int = 10
    semantic_timeout_seconds: float = 4.0
