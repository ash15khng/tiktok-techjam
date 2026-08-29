# Shopping Copilot MVP

## Purpose

The MVP finds the exact frozen-catalog `parent_asin` as early as possible without
requiring a network, GPU, or model API. Semantic models remain optional.

## Current flow

```text
message + Active State
    -> deterministic interpretation and override handling
    -> focused/exploratory route weighting
    -> field, title, category, category-popularity, and constraint FTS retrieval
    -> weighted Reciprocal Rank Fusion
    -> evidence, profile, and capped-popularity reranking
    -> unseen-first ordering, reset when intent changes
    -> answerability-weighted clarification; one broad recovery after a declined field
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
| Hit Rate@10 | 0.125 | 0.995 |
| MRR | 0.068 | 0.635 |
| MTTC | 9.81 | 2.245 |
| TechnicalScore | 0.107 | 0.863 |

These are development-set measurements, not private-set estimates. A 40-request
local broad-query audit measured 2.11 s startup and 261 ms p95 response latency.
The retained full-union rerank and broad clarification recovery improved recall
and first-hit turn. First-list ordering remains a tuning target.

## Semantic model status

`DisabledSemanticParser` is the offline default. An opt-in OpenAI Responses API
adapter now produces schema-validated query rewrites, subjective needs, and soft
slot hypotheses. It is gated to subjective or complex language, cannot generate
ASINs, and falls back to an empty semantic result on failure.

The adapter has only mocked contract tests because no API key is available.
Quality, latency, token cost, model choice, and end-to-end score must be measured
before enabling it for official runs. See [llm-integration.md](llm-integration.md).

## Tuning status

Route weights, candidate depths, the question threshold, and the popularity cap
are good-enough initial values. They need target-disjoint cross-validation before
being treated as final parameters.

See [findings.md](findings.md) for measured behavior and [todo.md](todo.md) for
remaining work and alternatives.
