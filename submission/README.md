# Shopping Copilot submission

This directory is the self-contained TechJam runtime package:

```text
submission/
  agent.py          organizer-facing `Agent` contract
  requirements.txt runtime dependencies
  README.md         setup and execution instructions
  src/              catalog, understanding, dialog, retrieval, and ranking code
```

## Requirements

- Python 3.10 or later
- The frozen catalog at `data/catalog.jsonl`
- No third-party package for the scored offline path

The optional SoCLaaS semantic parser requires network access and environment
variables documented in [`../docs/llm-integration.md`](../docs/llm-integration.md).
If it is disabled, unavailable, or fails, the deterministic offline agent
continues to return valid recommendations.

The complete runtime class map and per-class purpose notes are in
[`../docs/class-diagrams.md`](../docs/class-diagrams.md).

## Run and test

From the repository root:

```bash
python -m unittest discover -s tests -p "test_*.py"
python -m evaluator.local_evaluator
```

The organizer-facing import is:

```python
from submission.agent import Agent
```

`starter/agent.py` is retained only as a compatibility shim for the supplied
local evaluator.
