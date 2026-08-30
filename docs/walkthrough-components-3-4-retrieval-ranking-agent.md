# Walkthrough: Components 3 & 4 (Hybrid Retrieval, Multi-Signal Ranking, Clarification Policy & Agent Orchestration)

This document describes the design, architecture, modules, and end-to-end evaluation results for **Components 3 & 4** of the `ShoppingCopilot` pipeline, located under [`shopping_copilot/retrieval/`](../shopping_copilot/retrieval/), [`shopping_copilot/ranking/`](../shopping_copilot/ranking/), [`shopping_copilot/policy/`](../shopping_copilot/policy/), and [`shopping_copilot/agent.py`](../shopping_copilot/agent.py).

---

## 1. System Architecture & End-to-End Pipeline

Components 3 and 4 connect the multi-turn understanding & dialogue state tracker (Component 2) with the catalog indexing engine (Component 1) to perform sub-10ms retrieval, deterministic multi-signal ranking, and Gini-based adaptive clarification.

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│ ActiveState (from Component 2 StateReducer)                                             │
│  • Grounded category & hard/soft constraints                                            │
│  • Suppressed ANY attributes & exclusions                                               │
│  • Residual product keywords & raw semantic spans                                       │
└────────────────────────────────────────────┬────────────────────────────────────────────┘
                                             │
                                             ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│ RetrievalPlanner (shopping_copilot/retrieval/planner.py)                                │
│  • Continuous weight blending based on focus_score:                                     │
│    w_g = focus_score * w_focused + (1 - focus_score) * w_exploratory                    │
└────────────────────────────────────────────┬────────────────────────────────────────────┘
                                             │
                      ┌──────────────────────┼──────────────────────┐
                      ▼                      ▼                      ▼
           ┌──────────────────────┐┌──────────────────────┐┌──────────────────────┐
           │ TitleFTSGenerator    ││ FieldWeightedFTS     ││ AttributeCandidateGen│
           │ (FTS5 title search)  ││ (FTS5 all 6 fields)  ││ (Posting set inters) │
           └──────────┬───────────┘└──────────┬───────────┘└──────────┬───────────┘
                      │                      │                      │
                      └──────────────────────┼──────────────────────┘
                                             │
                                             ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│ WeightedRRFFusion (shopping_copilot/retrieval/fusion.py)                                │
│  • RRF(p) = sum_{g} (w_g / (60 + r_g(p)))                                               │
│  • CandidateEvidence aggregation across generators                                      │
└────────────────────────────────────────────┬────────────────────────────────────────────┘
                                             │
                                             ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│ LightweightReranker (shopping_copilot/ranking/reranker.py)                              │
│  • Tri-State Constraint Evaluation: match, contradiction, unknown                       │
│  • Hard Contradiction Demotion: Clean items strictly prioritized ahead of violations    │
│  • Multi-Signal Scoring: 0.55*RRF + 0.30*ConstraintSupport + 0.10*RawIDF + 0.05*Pop     │
└────────────────────────────────────────────┬────────────────────────────────────────────┘
                                             │
                                             ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│ QuestionPolicy (shopping_copilot/policy/question.py)                                    │
│  • Posterior-Weighted Partition Information Gain: Gini * coverage                       │
│  • Avoids active, suppressed (ANY), or previously asked attributes in the session       │
│  • Turn 10 finalization: Always outputs recommendations with ask_attribute = None       │
└────────────────────────────────────────────┬────────────────────────────────────────────┘
                                             │
                                             ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│ ShoppingAgent & Starter Agent (shopping_copilot/agent.py, starter/agent.py)             │
│  • Returns {"message": str, "ask_attribute": str | None, "recommendations": list}      │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Implemented Subsystems & Modules

### 2.1 Retrieval Subsystem (`shopping_copilot/retrieval/`)
- **[`models.py`](../shopping_copilot/retrieval/models.py)**: `RetrievalRequest`, `RetrievalPlan`, and `CandidateEvidence` tracking multi-generator ranks, raw scores, and constraint verification results.
- **[`lexical.py`](../shopping_copilot/retrieval/lexical.py)**: `TitleFTSGenerator` executing fast title-targeted queries and `FieldWeightedFTSGenerator` querying all 6 indexed catalog fields with category and exclusion filters.
- **[`attributes.py`](../shopping_copilot/retrieval/attributes.py)**: `AttributeCandidateGenerator` querying inverted posting sets, filtering price bounds, and scoring candidates using tri-state attribute matches.
- **[`fusion.py`](../shopping_copilot/retrieval/fusion.py)**: `WeightedRRFFusion` implementing normalized Reciprocal Rank Fusion across candidate pools.
- **[`assessment.py`](../shopping_copilot/retrieval/assessment.py)**: `RetrievalAssessor` calculating target-blind QPP metrics (generator agreement Jaccard, category entropy, and NQC dispersion).
- **[`planner.py`](../shopping_copilot/retrieval/planner.py)**: `RetrievalPlanner` blending generator weights and candidate pool depths according to the user's continuous `focus_score`.

### 2.2 Ranking Subsystem (`shopping_copilot/ranking/`)
- **[`constraints.py`](../shopping_copilot/ranking/constraints.py)**: `evaluate_constraint` implementing strict tri-state logic (`match`, `contradiction`, `unknown`). Products missing attribute data are treated strictly as `unknown` (0 penalty), ensuring ungrounded products are never penalized as contradictions.
- **[`reranker.py`](../shopping_copilot/ranking/reranker.py)**: `LightweightReranker` combining normalized constraint support, raw query IDF mass coverage, and logarithmic popularity priors while demoting products with hard contradictions.
- **[`belief.py`](../shopping_copilot/ranking/belief.py)**: `compute_candidate_belief` (softmax temperature distribution) and `compute_top10_confidence`.

### 2.3 Dialog Policy Subsystem (`shopping_copilot/policy/`)
- **[`models.py`](../shopping_copilot/policy/models.py)**: `ActionDecision` encapsulating the recommended ASINs, selected `ask_attribute`, and explanation message.
- **[`question.py`](../shopping_copilot/policy/question.py)**: `QuestionPolicy` identifying eligible attributes from `ALLOWED_ATTRIBUTES`, computing partition Gini impurity weighted by candidate coverage, avoiding repeated questions or suppressed attributes, and guaranteeing `ask_attribute = None` on turn 10.

### 2.4 End-to-End Orchestrator & Starter Integration
- **[`shopping_copilot/agent.py`](../shopping_copilot/agent.py)**: `ShoppingAgent` lifecycle manager orchestrating message interpretation, state reduction, candidate generation, fusion, reranking, and clarification policy.
- **[`starter/agent.py`](../starter/agent.py)**: Clean delegate wrapper preserving the exact evaluation interface.

---

## 3. Test Suite Verification

All 60 tests across unit and integration suites pass successfully:
```bash
python3 -m unittest discover -s tests -p "test_*.py" -v
```

Summary:
- **Retrieval Unit Tests** (`tests/unit/test_retrieval.py`): 5/5 passed.
- **Ranking Unit Tests** (`tests/unit/test_ranking.py`): 3/3 passed.
- **Policy Unit Tests** (`tests/unit/test_policy.py`): 3/3 passed.
- **End-to-End Agent Integration Tests** (`tests/integration/test_end_to_end_agent.py`): 1/1 passed.
- **Catalog & Indexing Tests** (`tests/unit/test_catalog.py`, `tests/unit/test_indexing.py`, `tests/integration/test_catalog_indexing_integration.py`): 17/17 passed.
- **Understanding & Dialog Tests** (`tests/unit/test_understanding.py`, `tests/unit/test_dialog.py`, `tests/unit/test_interpreter_corpus.py`, `tests/integration/test_scenarios_nlu.py`): 31/31 passed.

---

## 4. Benchmark Evaluation Results (Full 200 Public Dataset)

Evaluation executed via `python3 -m evaluator.local_evaluator`:

| Metric | Baseline Agent (`starter/agent.py`) | Production Shopping Copilot | Relative Improvement |
| :--- | :--- | :--- | :--- |
| **Hit Rate @ 10** | `12.50%` (25/200) | **`25.00%` (50/200)** | **+100.0% (2x)** |
| **MRR (Mean Reciprocal Rank)** | `0.0680` | **`0.0978`** | **+43.8%** |
| **MTTC (Mean Turns to Conversion)** | `9.81` | **`8.90`** | **-0.91 turns faster** |
| **Efficiency** | `0.1190` | **`0.2100`** | **+76.5%** |
| **Technical Score** | `0.1067` | **`0.1963`** | **+84.0%** |
| **Intent Override Hit Rate** | `16.67%` | **`33.33%`** | **+100.0% (2x)** |
| **Intent Override MRR** | `0.0933` | **`0.1833`** | **+96.5%** |
| **Reported Token Usage** | 0 tokens | **0 tokens** | Zero LLM overhead / deterministic |

