# Shopping Copilot MVP

## Purpose

The MVP finds the exact frozen-catalog `parent_asin` as early as possible without
requiring a network, GPU, or model API. Semantic models remain optional.

## Current flow

```text
message + Active State
    -> deterministic interpretation and override handling
    -> contextual short-answer resolution from the last question
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

For ordinary user wording, the deterministic parser separates inline budgets,
preferences, and exclusions (for example, `shoes under $60, preferably red, no
leather`). Numeric price scoring is three-valued: matching, violating, or
unknown when catalog price is missing.

Short answers such as `Nike`, `7`, or `80` inherit brand, size, or budget from
the immediately preceding structured question. Explicit current evidence still
wins: `leather` after a color question remains material. Bare `yes` is not added
as search evidence, while bare `no` suppresses the requested attribute.

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
| MRR | 0.068 | 0.636 |
| MTTC | 9.81 | 2.245 |
| TechnicalScore | 0.107 | 0.8633 |

These are development-set measurements, not private-set estimates. A 40-request
local broad-query audit measured 2.45 s startup and 265 ms p95 response latency.
The retained full-union rerank and broad clarification recovery improved recall
and first-hit turn. First-list ordering remains a tuning target.

## Semantic model status

`DisabledSemanticParser` is the offline default. An opt-in SoCLaaS
Responses-compatible adapter produces locally validated query rewrites,
subjective needs, and soft slot hypotheses. It is escalated only after a
deterministic retrieval-confidence check, cannot generate ASINs, and falls back
to the already-computed deterministic result on failure.

The provider is protected by a call cap and successful-result cache. A forced
client-executed function tool now requires a rewrite; function arguments are
still validated and grounded locally. Rewrites require a lexical anchor and soft
slots require exact evidence, sufficient confidence, and an accepted attribute.
Deterministic constraints always win. Retrieval runs a second time only when an
accepted semantic delta changes Active State.

The deterministic 14-case hard suite scores `0.857143` Hit Rate; an offline ideal
rewrite replay scores `1.000`. Two four-call live text-output passes produced no
accepted hints and no metric change, while three of eight requests failed. The
new function-tool request is covered only by mocked tests. See
[llm-integration.md](llm-integration.md).

## Tuning status

Route weights, candidate depths, the question threshold, and the popularity cap
are good-enough initial values. They need target-disjoint cross-validation before
being treated as final parameters.

See [findings.md](findings.md) for measured behavior and [todo.md](todo.md) for
remaining work and alternatives.
