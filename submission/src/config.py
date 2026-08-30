"""Immutable runtime configuration for retrieval, ranking, dialog, and semantics.

The values below are inputs to the agent, not learned probabilities. Comments
record the direction of each trade-off and the experiment that currently
justifies the setting. Keeping them together makes fold-based tuning auditable.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentConfig:
    """Configuration consumed by :class:`submission.src.agent.ShoppingAgent`."""

    # Contract limits. These match the published evaluator and are not tuning
    # knobs: lowering recommendations sacrifices scored slots; raising them has
    # no scoring effect because only the first ten valid unique IDs are used.
    max_turns: int = 10
    max_recommendations: int = 10

    # Retrieval depth. Raising a depth improves long-tail candidate recall but
    # increases latency; lowering it does the reverse. A rerank depth of 320 was
    # tested and slightly regressed score, while the bounded depth of 800
    # recovered deeper constraint matches, so 160/800 is retained.
    candidate_depth: int = 160
    category_pool_depth: int = 800
    rerank_depth: int = 800

    # RRF k controls rank decay: raising it makes generator ranks more alike;
    # lowering it rewards each generator's first results more sharply. The
    # standard k=60 starting point is retained; no controlled sweep is claimed.
    rrf_k: int = 60
    # More terms preserve verbose requests but broaden FTS work; fewer terms
    # reduce latency and can discard rare evidence. Current limits handled the
    # public and hard-language suites without truncation-related failures.
    max_query_terms: int = 40
    max_focused_terms: int = 12

    # Focus is sigmoid(intercept + preference_weight * preference/exclusion
    # count + category_weight * category presence). Raising either evidence
    # weight moves sooner toward focused retrieval; a higher intercept makes all
    # sessions more focused. These engineering defaults have not had a dedicated
    # coefficient sweep, so changes belong in controlled working-fold runs.
    focus_intercept: float = -1.10
    focus_preference_weight: float = 0.95
    focus_category_weight: float = 0.35

    # Each route weight increases that generator's influence when raised and
    # increases reliance on the other routes when lowered. A separate typed-
    # attribute route was tested and rejected (0.836906 versus 0.851762 on the
    # working folds); the retained five routes share evidence without it.
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

    # Candidate assessment uses top-N set overlap. Raising depth measures broader
    # agreement; raising the scale declares the same overlap more stable. The
    # present values preserve the retrieval-aware LLM gate on both evaluation
    # suites; no independent assessment sweep is claimed.
    assessment_overlap_depth: int = 20
    assessment_stability_scale: float = 2.50

    # Final-score weights. Raising one signal increases its influence relative
    # to the others. A structured-attribute scorer was tested and rejected
    # (0.844619 versus 0.851762), so the inspectable RRF, IDF, phrase, profile,
    # popularity, price, and exclusion signals remain.
    rerank_rrf_weight: float = 0.52
    rerank_idf_coverage_weight: float = 0.36
    rerank_exact_phrase_weight: float = 0.12
    profile_score_cap: float = 0.03
    popularity_weight: float = 0.18
    popularity_count_cap: int = 20_000
    budget_signal_weight: float = 0.12
    exclusion_penalty: float = 0.70

    # Clarification parameters. A higher threshold/ceiling asks fewer questions;
    # a lower value asks more and may hurt MTTC. More prior strength adapts more
    # slowly to this customer's replies. Broad recovery after a declined field
    # improved public TechnicalScore and is retained at one opportunity/session.
    question_candidate_depth: int = 50
    question_value_threshold: float = 0.08
    question_stability_weight: float = 0.55
    question_preference_saturation: float = 3.0
    question_prior_strength: float = 3.0
    unanswered_recovery_weight: float = 0.85
    broad_recovery_weight: float = 0.75
    broad_recovery_confidence_ceiling: float = 0.92

    # Optional semantic API controls. Larger time/input/output/call/cache values
    # increase coverage and cost or memory; smaller values fail or gate sooner.
    # Four seconds timed out in a live probe; six seconds allowed a ~4.2-second
    # success. A 50-session cap-2 ablation spent 437 tokens with no score gain,
    # so the feature stays disabled by environment unless deliberately enabled.
    semantic_timeout_seconds: float = 6.0
    semantic_max_input_chars: int = 4_000
    semantic_max_output_tokens: int = 220
    semantic_max_calls_per_run: int = 16
    semantic_cache_size: int = 256
    # Raising minimum confidence rejects more model slots; lowering it accepts
    # more weak inferences. Raising rewrite terms allows richer expansions but
    # increases drift risk. Requiring more exact-phrase terms suppresses more
    # model calls; requiring fewer may mistake generic matches for strong
    # evidence. Current grounding passed the frozen hard suite.
    semantic_min_confidence: float = 0.55
    semantic_max_rewrite_terms: int = 12
    semantic_exact_phrase_min_terms: int = 3
    # Higher stability thresholds call the model more often; higher minimum
    # terms calls it less often. Retrieval-aware gating removed both unnecessary
    # calls from the seeded 50-session sample while keeping 4/15 hard-suite turns.
    semantic_low_stability_threshold: float = 0.12
    semantic_ambiguous_category_stability: float = 0.40
    semantic_min_escalation_terms: int = 6
