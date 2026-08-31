# ShopScout

A conversational shopping agent built for the TechJam 2026 Conversational
E-Commerce Search Challenge.

## Project Overview

ShopScout is an offline-first conversational agent that finds a
customer's hidden target product within 10 conversational turns. Given an
anonymized customer profile and a short message, it asks at most one useful
clarification per turn and returns a ranked Top 10 of catalog products.

The system is fully deterministic by default (Python standard library +
SQLite FTS5, no model calls, $0 cost) with an optional, strictly gated LLM
adapter for harder natural-language cases. On the 200-session public
evaluator it scores:

| Metric | Baseline starter | ShopScout |
|---|---:|---:|
| Hit Rate@10 | 0.125 | **0.995** |
| MRR | 0.068 | **0.668** |
| MTTC (turns) | 9.81 | **2.34** |
| TechnicalScore | 0.107 | **0.871** |

Pipeline: a deterministic message parser turns each customer reply into
structured intent → a state reducer updates conversation memory → five
lexical retrieval routes are fused (Reciprocal Rank Fusion) → candidates are
reranked on term coverage, exact phrase, popularity, and budget fit → a
value-driven policy decides whether to ask a clarifying question.

## Key Differentiators & Technical Accomplishments

- **Zero-Cost Deterministic Core:** Achieves a **0.871 TechnicalScore** and **0.995 Hit Rate@10** using a 100% Python standard library + SQLite FTS5 pipeline running in ~27ms per turn with $0 default API spend.
- **Atomic State Overrides:** Models conversation memory as a stream of granular operations (`add`, `replace`, `exclude`) to handle mid-conversation preference reversals without erasing unaffected context.
- **Value-Gated Clarifications:** Combines entropy estimation and historical priors to ask at most one clarifying question per turn only when it meaningfully compresses the search space, cutting MTTC to **2.34 turns**.

## Setup and Installation

**Requirements:** Python 3.10+, SQLite with FTS5 (bundled in standard
CPython). No third-party packages needed for the default path.

```bash
# 1. Clone the repo
git clone <repo-url>
cd tiktok-techjam-sweekang-structural-retrieval

# 2. Get the frozen catalog (not included in the repo)
#    Download catalog.jsonl.gz + SHA256SUMS from the GitHub Release
sha256sum --check SHA256SUMS
gzip -dk catalog.jsonl.gz
mv catalog.jsonl data/catalog.jsonl

# 3. Install (empty by default — stdlib only)
python -m pip install -r submission/requirements.txt
```

Optional LLM adapter: copy `.env.example` to `.env` and set
`SHOPPING_COPILOT_LLM_ENABLED=1` plus your endpoint/key. It is off by default
and never required for scoring.

## Steps to Reproduce Results

From the repository root:

```bash
# Run unit + integration tests
python -m unittest discover -s tests -p "test_*.py"

# Run the hard-language stress suite
python -m tests.stress.hard_evaluator

# Run the official local evaluator on the 200 public sessions
python -m evaluator.local_evaluator
```

The last command writes `results.json` with per-session results and the
aggregate Hit Rate@10 / MRR / MTTC / TechnicalScore shown above. The
organizer-facing entry point is `submission.agent.Agent`;
`starter/agent.py` is only a compatibility shim for the provided evaluator.

To try it interactively, run the included Streamlit UI (`streamlit run
streamlit_app.py`) to chat with the agent turn by turn in a browser.

## Limitations and Future Improvements

- **Generalization risk:** weights were tuned on the 200 public sessions;
  performance on the organizer's 800 private sessions is unverified.
- **Complex language:** deterministic parsing is conservative on negation,
  OR-groups, metaphor, and implicit cross-category requests — an LLM rewrite
  layer showed measurable upside here but wasn't fully validated live.
- **Popularity bias:** the popularity prior can favor established products
  over niche ones (bounded so it can't remove valid Top-10 hits, but it does
  affect ordering).
- **Latency:** the six-route retrieval ensemble is slower on cold/unique
  queries than a simpler precomputed lookup would be.
- **With more time**, we would: live-validate the semantic adapter end to
  end, explore a lightweight cross-encoder reranker gated behind measured
  recall gains, and expand the hard-language regression suite.
