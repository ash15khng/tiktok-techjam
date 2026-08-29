# Shopping Copilot Pipeline — Quick Read

## Goal

Find the exact hidden catalog `parent_asin` in the Top 10, at the highest rank and earliest turn possible. Every usable turn returns up to ten valid recommendations; turns 1–9 normally also ask one informative question.

## Pipeline

```text
50k-product JSONL catalog
    -> validate ASINs and checksum
    -> Unicode normalization without inventing missing values
    -> SQLite FTS5 + category/attribute inverted indexes

reset(profile)
    -> immutable soft Customer Profile
    -> isolated SessionState

respond(message)
    -> deterministic operations: negate, replace, OR, range, ANY
    -> catalog trie grounding + conservative fuzzy linking
    -> IntentFrame of typed SlotUpdates and preserved raw phrases
    -> StateReducer creates current ActiveState
    -> NeedAssessor calculates specificity and focus_score
    -> title BM25 + field BM25 + attribute retrieval
    -> RetrievalAssessor measures agreement, entropy, NQC, coverage, and stability
    -> weighted Reciprocal Rank Fusion
    -> constraint match / contradiction / unknown evaluation
    -> lightweight reranking; optional dense/cross-encoder stage
    -> unseen-first Recommendation Exposure control
    -> CandidateBelief + target-blind Top10Confidence
    -> posterior-weighted clarification selection
    -> ResponseGuard validates exact ASINs and API shape
```

## Core algorithms

| Component | Algorithm |
|---|---|
| Text normalization | Unicode NFKC, casefolded lookup views, raw-text preservation |
| Operation parsing | Compiled regex and finite-state rules |
| Attribute grounding | Catalog-derived longest-match token trie |
| Fuzzy linking | Token Jaccard + `difflib.SequenceMatcher` + category compatibility |
| Lexical retrieval | SQLite FTS5 BM25 with field weights |
| Structured retrieval | Category/attribute posting-list set operations |
| Route control | Heuristic `focus_score`; all cheap generators still run |
| Retrieval confidence | Generator Jaccard, category entropy, NQC, margin, weight-perturbation stability |
| Fusion | Weighted Reciprocal Rank Fusion, `k=60` |
| Constraints | Three-valued logic: match, contradiction, unknown |
| Reranking | RRF + constraint support + raw phrase match + capped popularity |
| Across-turn novelty | Stable unseen-first partition with reset on Intent Override |
| Question selection | Candidate-belief-weighted partition gain and simulated rank gain |
| Optional semantics | MiniLM embeddings and Top-30 cross encoder with timeout/fallback |

## Chosen technologies

The reliable path uses Python 3.10+, the standard library, SQLite FTS5, JSONL, dataclasses, enums, protocols, and `unittest`. It has no required network, LLM, GPU, or vector-database dependency.

Optional measured stages use:

- NumPy exact dot-product retrieval;
- `sentence-transformers/all-MiniLM-L6-v2` embeddings;
- `cross-encoder/ms-marco-MiniLM-L-6-v2` over at most 30 candidates;
- a schema-constrained `SemanticParser` provider with deterministic fallback.

## Important semantics

- `focus_score` is an uncalibrated routing control, not Buying probability.
- `NeedAssessment` describes the expressed need; `RetrievalAssessment` describes search quality.
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
3. Add title, field, and attribute generators with uniform RRF.
4. Add Need and Retrieval assessments plus tri-state reranking.
5. Add CandidateBelief and adaptive questions.
6. Add dense retrieval or a model only for a measured failure.

## Evaluation order

1. candidate target recall at 10/50/100/300;
2. Hit Rate@10;
3. MRR;
4. MTTC and hit-turn distribution;
5. Buying, Browsing, Override, and Boundary regressions;
6. latency, memory, tokens, cost, and fallback rate.

Published starter: Hit Rate@10 `0.125`, MRR `0.068034`, MTTC `9.81`.

See [architecture.md](architecture.md) for formulas, contracts, module paths, thresholds, tests, ownership, fallbacks, and ablations.
