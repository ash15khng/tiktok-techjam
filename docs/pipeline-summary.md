# Shopping Copilot Pipeline — Quick Read

## Goal

Find the exact hidden catalog `parent_asin` in the returned Top 10, at the highest possible rank and on the earliest possible turn. The Agent has at most 10 turns and should normally recommend up to 10 valid products on every turn, including when it asks a clarification.

## Pipeline in one view

```text
Frozen 50k-product JSONL catalog
    -> validate and normalize without inventing missing values
    -> build immutable in-memory product and search indexes

reset(profile)
    -> create isolated SessionState with profile as soft evidence

respond(message)
    -> extract typed constraints, exclusions, corrections, and subjective needs
    -> apply deterministic state updates and Intent Override replacement
    -> estimate decision stage and continuous focus_probability
    -> run title FTS + field FTS + category/attribute retrieval
    -> diagnose candidate agreement, spread, evidence coverage, and stability
    -> recalibrate generator weights; optionally gate dense retrieval
    -> fuse ranks with Reciprocal Rank Fusion
    -> evaluate constraints as match / contradiction / unknown
    -> rerank and estimate target-blind Top-10 confidence
    -> recommend, or ask one high-value attribute and recommend
    -> validate exact catalog ASINs, uniqueness, Top-10 limit, and usage
```

## Main architectural ideas

- **Soft intent routing:** intent is a continuous `focus_probability`, not a hard Buying/Browsing switch. All cheap generators remain eligible.
- **Two-pass planning:** language and state create the initial retrieval plan; candidate diagnostics recalibrate it.
- **State over chat concatenation:** retrieval uses current active constraints, not stale historical text.
- **Override correctness:** corrections replace incompatible state before the next retrieval.
- **Three-valued evidence:** missing metadata is `unknown`, never an automatic contradiction.
- **Always recommend:** a clarification normally accompanies recommendations so the current turn retains a hit opportunity.
- **Metric-aware questions:** ask only when expected next-turn Top-10 gain justifies answerability risk and MTTC cost.
- **Inspectable ranking:** preserve generator ranks, constraint results, reason codes, latency, and fallback behavior.

## Candidate and ranking stages

| Stage | Purpose |
|---|---|
| Title FTS | Precise product and category matching |
| Field-weighted FTS | Recall from title, categories, features, details, store, and description |
| Category/attribute retrieval | Explicit category, material, color, size, style, brand, budget, feature, and use-case evidence |
| Optional dense retrieval | Subjective needs and vocabulary mismatch when lexical agreement is weak |
| Reciprocal Rank Fusion | Combine incomparable generator rankings |
| Constraint evaluator | Partition verified matches, unknowns, and contradictions |
| Lightweight reranker | Improve Top-10 ordering and MRR |
| Optional semantic reranker | Cost-gated Top-N refinement with timeout and deterministic fallback |

## Key data structures

- `ProductRecord`: immutable raw and normalized catalog evidence.
- `IntentFrame`: one-message interpretation and proposed slot updates.
- `SessionState`: active constraints, exclusions, profile, prior actions, and diagnostics.
- `RetrievalRequest`: immutable current-state snapshot for generators.
- `RetrievalPlan`: generator weights, depths, and optional-stage gates.
- `CandidateHit`: per-generator ranks, constraint results, scores, and explanations.
- `Top10Confidence`: target-blind stability and evidence estimate.
- `ActionDecision`: recommend or ask-and-recommend with reason codes.

## Key technologies

| Technology | Use |
|---|---|
| Python 3.10+ | Agent, typed domain models, orchestration, tests |
| SQLite FTS5 / BM25 | Fast in-memory lexical indexes and deterministic fallback |
| JSONL | Official frozen catalog and public sessions |
| Dataclasses, enums, protocols, type hints | Stable module contracts and state transitions |
| Catalog-derived normalized indexes | Category and attribute grounding without external histories |
| Reciprocal Rank Fusion | Rank-level hybrid retrieval fusion |
| Standard-library `unittest` | Fast deterministic unit and integration tests |
| Official local evaluator | Hit Rate@10, MRR, MTTC, Efficiency, scenario metrics |
| Optional local embeddings | Dense semantic candidate retrieval if measured recall requires it |
| Optional LLM API/local model | Structured interpretation or Top-N reranking only when measured and budgeted |

The reliable path must remain functional without optional embeddings or an LLM.

## Code ownership map

| Area | Planned location |
|---|---|
| Official Agent adapter | `starter/agent.py` |
| Orchestration and response guard | `shopping_copilot/agent.py`, `shopping_copilot/contracts.py` |
| Catalog cleaning and indexes | `shopping_copilot/catalog/` |
| Message and intent understanding | `shopping_copilot/understanding/` |
| Session state and question policy | `shopping_copilot/dialog/` |
| Candidate generation and fusion | `shopping_copilot/retrieval/` |
| Constraint and semantic reranking | `shopping_copilot/ranking/` |
| Runtime diagnostics and traces | `shopping_copilot/observability/` |
| Unit and scenario tests | `tests/unit/`, `tests/integration/` |

## Evaluation priority

1. Target recall at candidate depths 10/50/100/300.
2. Immediate Top-10 Hit Rate.
3. MRR within the Top 10.
4. Hit-turn distribution and MTTC.
5. Scenario regressions, especially Override and Boundary.
6. Latency, memory, tokens, cost, and fallback rate.

Published starter baseline: Hit Rate@10 `0.125`, MRR `0.068034`, MTTC `9.81`.

## First implementation sequence

1. Reproduce the starter through the new immutable `CatalogStore`.
2. Add typed message parsing and state reduction.
3. Add multiple cheap generators with uniform fusion and candidate-recall logging.
4. Add soft focus blending and two-pass diagnostic calibration.
5. Add tri-state constraint reranking and Top-10 confidence.
6. Add the always-recommend question policy.
7. Consider dense retrieval or an LLM only after a measured failure identifies the need.

For full contracts, tests, ownership, experiment order, options, and references, see [architecture.md](architecture.md).
