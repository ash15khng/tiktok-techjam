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

reset(profile)
    -> copied soft Customer Profile
    -> isolated SessionState

respond(message)
    -> deterministic category/payload/correction/exclusion/ANY parsing
    -> explicit-or-contextual short reply resolution with provenance
    -> optional gated, schema-constrained semantic hints
    -> IntentFrame of typed SlotUpdates and preserved phrases
    -> StateReducer creates current ActiveState
    -> sigmoid focus score from current category/constraint evidence
    -> title/field BM25 + category relevance/popularity + constraint retrieval
    -> weighted Reciprocal Rank Fusion
    -> generator overlap and Top-10 stability assessment
    -> full-union lightweight reranking
    -> unseen-first Recommendation Exposure control
    -> candidate coverage/Gini clarification or one broad recovery
    -> ResponseGuard validates exact ASINs and API shape
```

## Core algorithms

| Component | Algorithm |
|---|---|
| Text normalization | Unicode NFKC, casefolded lookup views, raw-text preservation |
| Operation parsing | Rules for correction, payload, exclusion, and no-preference language |
| Short replies | Explicit evidence first; immediate question context second; bounded fallback |
| Lexical retrieval | SQLite FTS5 BM25 with field weights |
| Broad-category coverage | Shared 800-item category pool, ranked separately by BM25 and rating count |
| Route control | Heuristic `focus_score`; all cheap generators still run |
| Retrieval confidence | Pairwise generator Top-20 Jaccard converted to Top-10 stability |
| Fusion | Weighted Reciprocal Rank Fusion, `k=60` |
| Reranking | Full bounded union: RRF + IDF/phrase coverage + capped popularity + missing-neutral price range |
| Across-turn novelty | Stable unseen-first partition with reset on Intent Override |
| Question selection | Top-50 coverage/Gini partition value plus one broad unanswered-question recovery |
| Optional semantics | OpenAI Responses schema adapter, gated and disabled without explicit environment opt-in |

## Chosen technologies

The reliable path uses Python 3.10+, the standard library, SQLite FTS5, JSONL, dataclasses, enums, protocols, and `unittest`. It has no required network, LLM, GPU, or vector-database dependency.

The optional semantic adapter uses the OpenAI Responses API behind a protocol
with deterministic fallback. It has mocked contract tests only. NumPy/MiniLM
dense retrieval and a Top-N cross encoder remain unimplemented alternatives.

## Important semantics

- `focus_score` is an uncalibrated routing control, not Buying probability.
- `RetrievalAssessment` describes generator coherence, not customer intent.
- the interpreter proposes events; only `StateReducer` changes active state.
- missing product metadata is `unknown`, never contradiction.
- raw feature text remains searchable even when it cannot be safely normalized.
- an Intent Override deactivates stale values before retrieval.
- an Intent Override resets Recommendation Exposure because earlier rejection used a different need.
- `ANY` clears and suppresses an attribute and prevents repeat questions.
- ask-and-recommend preserves the current hit opportunity, so the main question is which attribute to ask.

## Implementation order

1. Reproduce the starter through `CatalogStore` and `ResponseGuard`.
2. Add deterministic interpretation and Active State.
3. Add five lexical rank lists and weighted RRF. **Done.**
4. Add full-union lightweight reranking and exposure control. **Done.**
5. Add adaptive specific questions and one broad recovery. **Done.**
6. Add tri-state structured constraints, dense retrieval, or model reranking only
   for a measured remaining failure. **Deferred.**

## Evaluation order

1. candidate target recall at 10/50/100/300;
2. Hit Rate@10;
3. MRR;
4. MTTC and hit-turn distribution;
5. Buying, Browsing, Override, and Boundary regressions;
6. latency, memory, tokens, cost, and fallback rate.

Published starter: Hit Rate@10 `0.125`, MRR `0.068034`, MTTC `9.81`.

See [architecture.md](architecture.md) for formulas, contracts, module paths, thresholds, tests, ownership, fallbacks, and ablations.
