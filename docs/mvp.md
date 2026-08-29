# Shopping Copilot MVP

## Purpose

The MVP finds the exact frozen-catalog `parent_asin` as early as possible without
requiring a network, GPU, or model API. Semantic models remain optional.

## Current flow

```text
message + Active State
    -> deterministic interpretation and override handling
    -> focused/exploratory route weighting
    -> field, title, category, and constraint FTS retrieval
    -> weighted Reciprocal Rank Fusion
    -> evidence, profile, and capped-popularity reranking
    -> answerability-weighted clarification and recommendations
    -> explanation and contract validation
```

Missing metadata is not treated as a contradiction. Explicit session evidence
overrides the anonymized profile. Corrections remove stale evidence before the
next retrieval.

## Runtime boundaries

- `starter/agent.py` exposes the official interface.
- `shopping_copilot/agent.py` coordinates one response.
- `catalog/` owns immutable products and search indexes.
- `understanding/` converts messages into typed proposed updates.
- `dialog/` owns Active State and clarification decisions.
- `retrieval/` produces and fuses candidates.
- `ranking/` applies constraints and orders recommendations.

The runtime never reads public labels, hidden intent cards, or evaluator code.
Only valid catalog IDs can leave the response guard.

## Canonical commands

```bash
python -m unittest discover -v
python -m evaluator.local_evaluator
```

Place the verified catalog at `data/catalog.jsonl` before evaluation.

## Public-set result

The unmodified official evaluator currently reports:

| Metric | Baseline | MVP |
|---|---:|---:|
| Hit Rate@10 | 0.125 | 0.920 |
| MRR | 0.068 | 0.628 |
| MTTC | 9.81 | 3.26 |
| TechnicalScore | 0.107 | 0.803 |

These are development-set measurements, not private-set estimates. A 40-request
local audit measured 2.37 s startup and 470 ms p95 response latency.

## Semantic model status

`DisabledSemanticParser` is the offline default. A future provider may return
validated query rewrites and subjective needs, but it cannot generate ASINs.
Provider evaluation, timeouts, cost, and parameter tuning remain required before
enabling it for official runs. The deterministic path remains the fallback.

## Tuning status

Route weights, candidate depths, the question threshold, and the popularity cap
are good-enough initial values. They need target-disjoint cross-validation before
being treated as final parameters.

See [findings.md](findings.md) for measured behavior and [todo.md](todo.md) for
remaining work and alternatives.
