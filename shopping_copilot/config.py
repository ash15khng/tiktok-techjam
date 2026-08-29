"""Runtime configuration shared by the deterministic MVP components."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MVPConfig:
    """Small, explicit set of MVP controls.

    Values are initial engineering guesses. They must be tuned with controlled
    public-set experiments rather than treated as learned probabilities.
    """

    candidate_depth: int = 160
    category_pool_depth: int = 800
    rerank_depth: int = 160
    rrf_k: int = 60
    max_query_terms: int = 40
    max_focused_terms: int = 12
    max_recommendations: int = 10
    semantic_timeout_seconds: float = 4.0
    semantic_max_input_chars: int = 4_000
    semantic_max_output_tokens: int = 500
    profile_score_cap: float = 0.03
    popularity_weight: float = 0.18
    popularity_count_cap: int = 20_000
    question_value_threshold: float = 0.08

    # Initial guesses: retain only after scenario-level tuning and ablation.
    focused_route_weights: tuple[tuple[str, float], ...] = (
        ("constraint", 1.60),
        ("field", 1.00),
        ("title", 0.55),
        ("category", 0.45),
        ("category_popular", 0.35),
    )
    exploratory_route_weights: tuple[tuple[str, float], ...] = (
        ("constraint", 0.85),
        ("field", 1.00),
        ("title", 0.95),
        ("category", 1.05),
        ("category_popular", 0.95),
    )
