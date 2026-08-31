# Shopping Copilot Pipeline — Quick Read

## Goal

Find the exact hidden catalog `parent_asin` in the Top 10, at the highest rank and earliest turn possible. Every usable turn returns up to ten valid recommendations; turns 1–9 normally also ask one informative question.

## Pipeline

```text
50k-product JSONL catalog
    -> externally verify published checksum
    -> validate non-empty unique ASINs while loading
    -> normalized searchable views without inventing missing values
    -> product map + SQLite FTS5 + vocabulary frequencies
    -> compact most-specific category buckets + bounded per-agent caches
    -> catalog-derived attribute values + answerability priors
    -> log-quantile price bands; missing price remains unknown

reset(profile)
    -> copied soft Customer Profile
    -> isolated SessionState

respond(message)
    -> return a cached snapshot for duplicate/late turns without replaying state
    -> deterministic category/payload/correction/exclusion/ANY parsing
    -> independent add/replace/exclude/set_any operations in compound turns
    -> explicit-or-contextual short reply resolution with provenance
    -> IntentFrame of typed SlotUpdates and preserved phrases
    -> optional pre-retrieval semantic parse for compound/unresolved language
    -> StateReducer creates current ActiveState
    -> sigmoid focus score from current category/constraint evidence
    -> title/field BM25 + category relevance/popularity + constraint retrieval
    -> catalog-structural route only after positive preference evidence
    -> weighted Reciprocal Rank Fusion
    -> generator overlap and Top-10 stability assessment
    -> full-union lightweight reranking
    -> optional retrieval-aware semantic escalation if preflight skipped
       -> strict function-tool interpretation and local grounding
       -> one reretrieval only when accepted evidence changes state
    -> unseen-first Recommendation Exposure control
    -> freeze Top-10 membership; apply bounded secondary ordering
       -> popularity tie-break disabled after Intent Override
    -> candidate coverage/Gini clarification or one broad recovery
       -> per-session answer/decline posterior updates remaining question value
    -> ResponseGuard validates exact ASINs and API shape
```

## Core algorithms

| Component | Algorithm |
|---|---|
| Text normalization | Unicode NFKC, casefolded lookup views, raw-text preservation |
| Operation parsing | Rules for correction, payload, exclusion, and no-preference language |
| Attributes and short replies | Fixed API schema, catalog-derived value registry; explicit evidence first; immediate question context second |
| Lexical retrieval | SQLite FTS5 BM25 with field weights |
| Broad-category coverage | Shared 800-item category pool, ranked separately by BM25 and rating count |
| Structural retrieval | Exact/contained/suffix category resolution; phrase coverage, token coverage, then popularity |
| Route control | Heuristic `focus_score`; all cheap generators still run |
| Retrieval confidence | Pairwise generator Top-20 Jaccard converted to Top-10 stability |
| Fusion | Weighted Reciprocal Rank Fusion, `k=60` |
| Reranking | Full bounded union: RRF + IDF/phrase coverage + capped popularity + missing-neutral price range |
| Across-turn novelty | Stable unseen-first partition with reset on Intent Override |
| Final list safety | Freeze the selected Top 10, then apply bounded ordering; weak priors cannot change membership |
| Question selection | Top-50 coverage/Gini × catalog prior × session posterior, plus one broad recovery |
| Optional semantics | Pre/post retrieval gates + all-field operation schema + process/session caps + cache + local grounding |

## Chosen technologies

The reliable path uses Python 3.10+, the standard library, SQLite FTS5, JSONL, dataclasses, enums, protocols, and `unittest`. It has no required network, LLM, GPU, or vector-database dependency.

The optional semantic adapter uses a SoCLaaS Responses-compatible API behind a
protocol with deterministic fallback. The 14-case hard suite measures language
outside the public simulator. An offline ideal-rewrite replay recovered both
deterministic misses, but two capped live text-output runs produced no accepted
hints. A strict forced function-tool path is now mocked but not live-validated.
Unimplemented alternatives are listed only in [`../TODO.md`](../TODO.md).

## Important semantics

- `focus_score` is an uncalibrated routing control, not Buying probability.
- `RetrievalAssessment` describes generator coherence, not customer intent.
- the interpreter proposes events; only `StateReducer` changes active state.
- missing product metadata is `unknown`, never contradiction.
- catalog values generalize beyond code word lists, but remain closed to the frozen catalog; the optional LLM handles true language gaps.
- raw feature text remains searchable even when it cannot be safely normalized.
- an Intent Override deactivates stale values before retrieval.
- an Intent Override resets Recommendation Exposure because earlier rejection used a different need.
- `ANY` clears and suppresses an attribute and prevents repeat questions.
- `asked_attributes` prevents answerability from repeating a field within one
  intent; a genuine category replacement resets that history.
- LLM rewrites are separate search evidence, not durable customer facts.
- ask-and-recommend preserves the current hit opportunity, so the main question is which attribute to ask.

## Implemented stages

1. `CatalogStore` and `ResponseGuard` provide the reliable contract path.
2. Deterministic interpretation and Active State preserve current intent.
3. Five lexical rank lists plus one evidence-gated structural list feed weighted RRF.
4. Full-union reranking and exposure control order the final candidates.
5. A membership-preserving orderer improves rank without delaying target hits.
6. Adaptive specific questions and one broad recovery guide later turns.

A separate typed-attribute candidate route and positive structured reranker were
tested on the four development folds and rejected. They duplicated existing
constraint evidence, lowered the score, and increased latency. The retained
system retains those five independently weighted lists before adding the
different catalog-family signal and feature-based reranker.

Remaining work and alternative implementations are centralized in
[`../TODO.md`](../TODO.md).

## Evaluation order

1. candidate target recall at 10/50/100/300;
2. Hit Rate@10;
3. MRR;
4. MTTC and hit-turn distribution;
5. Buying, Browsing, Override, and Boundary regressions;
6. latency, memory, tokens, cost, and fallback rate.

The public-development protocol held 20% out during numeric tuning and used four
scenario-stratified, target/title-family-disjoint working folds. The held-out
partition was later included in the final compatibility replay. See
[evaluation-methodology.md](evaluation-methodology.md).

Published starter: Hit Rate@10 `0.125`, MRR `0.068034`, MTTC `9.81`.

Current public compatibility replay: Hit Rate@10 `0.995`, MRR `0.667556`,
MTTC `2.335`, and TechnicalScore `0.871067`, with zero model tokens. Comparative
latency, memory, cost, and score trade-offs are in
[differentiation.md](differentiation.md).

See [architecture.md](architecture.md) for formulas, contracts, module paths, thresholds, tests, ownership, fallbacks, and ablations.
