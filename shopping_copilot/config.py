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
    rerank_depth: int = 800
    rrf_k: int = 60
    max_query_terms: int = 40
    max_focused_terms: int = 12
    max_recommendations: int = 10
    # Provisional from a live gateway probe; retune from a larger latency sample.
    semantic_timeout_seconds: float = 6.0
    semantic_max_input_chars: int = 4_000
    semantic_max_output_tokens: int = 220
    semantic_max_calls_per_run: int = 16
    semantic_cache_size: int = 256
    semantic_min_confidence: float = 0.55
    semantic_max_rewrite_terms: int = 12
    # Initial escalation guesses; tune on target-independent language cases.
    semantic_low_stability_threshold: float = 0.12
    semantic_ambiguous_category_stability: float = 0.40
    semantic_min_escalation_terms: int = 6
    profile_score_cap: float = 0.03
    popularity_weight: float = 0.18
    popularity_count_cap: int = 20_000
    budget_signal_weight: float = 0.12
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
