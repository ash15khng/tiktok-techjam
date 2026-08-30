"""
Runtime configuration for retrieval, ranking, dialog, and semantics.

These values were obtained through staring hard at outputs.
It is possible/advisable to further tune them.

Trade-offs are commented.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentConfig:
    # Configuration consumed by :class:`submission.src.agent.ShoppingAgent`

    # Competition definied. do not edit.
    max_turns: int = 10
    max_recommendations: int = 10

    # Retrieval depths. 
    # Raising any of the depths improves long-tail candidate recall but increases latency; 
    ## Long tail recall refers to surfacing less popular items that may be more relevant to the user's query
    candidate_depth: int = 160 # items from initial generation PER route (we have 5 routes, so 5*160=800 candidates before reranking)
    category_pool_depth: int = 800 # candidates filtered from category search, to be merged.
    rerank_depth: int = 800 # items passed to reranker

    # RRF controls
    # lowering k makes it sharply rewards top results.
    # standard k=60 starting point is retained, value not experimented on
    rrf_k: int = 60

    # Query term limits. 
    # More terms preserve verbose requests but increase text search load
    # fewer reduce latency and risk dropping evidence.
    max_query_terms: int = 40 # Max terms allowed in general queries
    max_focused_terms: int = 12 # Max terms allowed for focused queries

    # Focus scoring formula parameters. 
    # Focus = sigmoid(intercept + preference_weight * count + category_weight * presence).
    # Raising either evidence weight moves sooner toward focused retrieval
    # a higher intercept makes all sessions more focused.
    # not much experimentation was done on these values
    focus_intercept: float = -1.10
    focus_preference_weight: float = 0.95
    focus_category_weight: float = 0.35

    # Multi-route generator influence weights. 
    # Each route weight increases that generator's influence when raised i.e. increases reliance on the other routes when lowered. 
    # A separate typed-attribute route should be tested again for generalisations.
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

    # Candidate assessment via top-N set overlap.
    # larger overlap_depth increases the number of top results considered for overlap, which can improve stability but may reduce responsiveness to new information i.e. measure broad scope of agreement
    assessment_overlap_depth: int = 20
    assessment_stability_scale: float = 2.50

    # Final-score weights.
    rerank_rrf_weight: float = 0.52
    rerank_idf_coverage_weight: float = 0.36
    rerank_exact_phrase_weight: float = 0.12
    profile_score_cap: float = 0.03
    popularity_weight: float = 0.18
    popularity_count_cap: int = 20_000
    budget_signal_weight: float = 0.12
    exclusion_penalty: float = 0.70

    # Clarification parameters. 
    # higher threshold/ceiling asks fewer questions
    # More prior strength adapts more slowly to this customer's replies. 
    # Broad recovery after a declined field improved TechnicalScore and is retained at one opportunity/session.
    question_candidate_depth: int = 50
    question_value_threshold: float = 0.08
    question_stability_weight: float = 0.55
    question_preference_saturation: float = 3.0
    question_prior_strength: float = 3.0
    unanswered_recovery_weight: float = 0.85
    broad_recovery_weight: float = 0.75
    broad_recovery_confidence_ceiling: float = 0.92

    # Semantic API controls. 
    # Larger time/input/output/call/cache values increase coverage and cost or memory
    # smaller values fail or gate sooner
    # 4s timed out in a live probe
    # 6s allowed a ~4.2-second success.
    semantic_timeout_seconds: float = 6.0
    semantic_max_input_chars: int = 4_000
    semantic_max_output_tokens: int = 220
    semantic_max_calls_per_run: int = 16
    semantic_cache_size: int = 256

    # Semantic grounding thresholds and terms.
    # min_confidence: refers to the minimum confidence threshold for semantic grounding.
    # rewrite_terms: how much the llm is able to rewrite; richer expansions but increases drift risk. 
    # exact_phrase_min_terms: how many terms must match exactly to be considered a strong match; more terms suppresses model calls, fewer may mistake generic matches for strong evidence.
    # low_stability_threshold: controls when to call the model more often
    semantic_min_confidence: float = 0.55
    semantic_max_rewrite_terms: int = 12
    semantic_exact_phrase_min_terms: int = 3
    semantic_low_stability_threshold: float = 0.12
    semantic_ambiguous_category_stability: float = 0.40
    semantic_min_escalation_terms: int = 6
