# Shopping Copilot MVP

## Purpose

The MVP finds the exact frozen-catalog `parent_asin` as early as possible while
remaining useful when model APIs are unavailable. It preserves one deterministic
path and treats semantic models as optional improvements.

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

## Semantic model status

`DisabledSemanticParser` is the offline default. A future provider may return
validated query rewrites and subjective needs, but it cannot generate ASINs.
Provider evaluation, timeouts, cost, and parameter tuning remain required before
enabling it for official runs.
