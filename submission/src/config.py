"""
Runtime configuration for retrieval, ranking, dialog, and semantics.

The comments beside tuned values describe the direction of their trade-offs.
Values without a completed ablation are explicitly marked for further tuning.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentConfig:
    # Configuration consumed by :class:`submission.src.agent.ShoppingAgent`

    # Competition-defined output limits. Do not edit.
    max_turns: int = 10
    max_recommendations: int = 10

    # Retrieval depths. Raising them improves long-tail candidate recall but
    # increases latency and memory. Candidate depth applies to each of 5 routes.
    candidate_depth: int = 160
    category_pool_depth: int = 800
    rerank_depth: int = 800

    # RRF controls
    # Lowering k rewards top-ranked route results more sharply. The conventional
    # k=60 starting point is retained; it still needs target-disjoint tuning.
    rrf_k: int = 60

    # More terms preserve verbose requests but increase search load; fewer terms
    # reduce latency but risk dropping evidence.
    max_query_terms: int = 40
    max_focused_terms: int = 12

    # Focus scoring formula parameters.
    # Focus = sigmoid(intercept + preference_weight * count + category_weight * presence).
    # Raising either evidence weight moves sooner toward focused retrieval
    # a higher intercept makes all sessions more focused.
    # not much experimentation was done on these values
    focus_intercept: float = -1.10
    focus_preference_weight: float = 0.95
    focus_category_weight: float = 0.35

    # Raising a route weight increases that generator's influence; lowering it
    # transfers influence to the other routes.
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
    # Catalog-structural route: category-bucket ranking by exact phrase
    # coverage, token coverage, and popularity. Disabling it removes its index,
    # startup cost, and RRF evidence while preserving the five lexical routes.
    structural_retrieval_enabled: bool = True
    # One disclosed positive phrase is required before the structural scorer
    # joins fusion. Lowering this to zero makes category popularity influence
    # vague Browsing turns; the first sweep showed that reduced Browsing MRR.
    structural_min_preference_phrases: int = 1
    # Raising these values improves structural target discovery but can freeze
    # a weaker early rank; lowering them preserves more lexical ordering. The
    # retained 0.80/0.50 plateau improved HR, MRR, MTTC, and score on the 160
    # working sessions, while 1.20/0.90 lowered aggregate score.
    structural_focused_weight: float = 0.80
    structural_exploratory_weight: float = 0.50

    # Candidate assessment via top-N set overlap.
    # Larger overlap depth measures agreement across a broader result window but
    # can make the stability estimate less responsive to new evidence.
    assessment_overlap_depth: int = 20
    assessment_stability_scale: float = 2.50

    # Final-score weights.
    rerank_rrf_weight: float = 0.52
    rerank_idf_coverage_weight: float = 0.36
    rerank_exact_phrase_weight: float = 0.12
    # When enabled, a secondary stage reorders only frozen Top-10 IDs. Existing
    # membership signals remain intact because removing their weak priors delayed
    # public working-fold hits; this flag contains only the additional stage.
    membership_preserving_ordering: bool = True
    # Raising this value promotes products containing complete disclosed phrases;
    # lowering it preserves the relevance order more strictly. Zero disables the
    # pool scan. A 0.15 experiment added latency and did not improve the retained
    # combined candidate, so zero is the current measured setting.
    phrase_rarity_order_weight: float = 0.0
    # More pool candidates yield a steadier rarity estimate but add string scans;
    # fewer reduce latency but can mistake a common phrase for a rare one.
    phrase_rarity_pool_depth: int = 50
    # Longer phrases preserve verbose evidence but increase drift and scan cost;
    # shorter phrases are cheaper but less discriminative.
    phrase_rarity_max_terms: int = 12
    # These weights affect order only after Top-10 membership is frozen. Raising
    # either promotes the corresponding weak prior without changing HitRate@10;
    # zero preserves the relevance order. Both require isolated validation.
    ordering_popularity_weight: float = 0.05
    ordering_profile_weight: float = 0.0
    # Enabling this lets a weak catalog prior reorder corrected intents; leaving
    # it false protects explicit override evidence. The safer false setting is
    # retained unless target-disjoint override results improve.
    ordering_popularity_during_override: bool = False
    profile_score_cap: float = 0.03
    popularity_weight: float = 0.18
    popularity_count_cap: int = 20_000
    budget_signal_weight: float = 0.12
    exclusion_penalty: float = 0.70

    # Clarification parameters.
    # higher threshold/ceiling asks fewer questions
    # More prior strength adapts more slowly to this customer's replies. 
    # One broad recovery after a declined field improved TechnicalScore.
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
    # A lower per-session cap bounds worst-case user latency/cost; raising it can
    # recover more unrelated language failures across ten turns. Two permits one
    # early interpretation and one later correction, but has not been tuned.
    semantic_max_calls_per_session: int = 2
    semantic_cache_size: int = 256

    # Semantic grounding thresholds and terms.
    # Higher confidence rejects more uncertain fields; lower accepts more noise.
    # More rewrite terms preserve richer expansions but increase drift risk.
    # More exact-phrase terms suppress fewer calls; fewer can mistake generic
    # overlap for strong evidence. A higher stability threshold calls more often.
    semantic_min_confidence: float = 0.55
    semantic_max_rewrite_terms: int = 12
    semantic_exact_phrase_min_terms: int = 3
    semantic_low_stability_threshold: float = 0.12
    semantic_ambiguous_category_stability: float = 0.40
    semantic_min_escalation_terms: int = 6
