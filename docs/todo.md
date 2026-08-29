# MVP To-do and Alternatives

## Prioritized work

1. Design and ablate a target-blind long-tail candidate route for the one
   remaining public miss; do not tune directly to its ASIN.
2. Measure target recall at candidate depths 10, 50, 100, 160, and 800 per route.
3. Improve first-turn MRR without regressing the retained 0.995 Hit Rate and
   2.245 MTTC.
4. Tune route weights, rerank weights, popularity cap, question threshold, and
   candidate depth with target-ASIN-disjoint folds.
5. Add explicit tri-state constraint evidence: match, contradiction, or unknown.
6. Add configuration hashes and optional per-turn traces without hidden labels.
7. Evaluate the implemented schema-validated semantic parser with a real key,
   recording parse quality, timeout rate, tokens, latency, cost, and score delta.
8. Grow the current real-user examples into at least 100 parser utterances with
   operation and slot expectations.
9. Rerun latency and memory on the judging environment; local measurements are
   261 ms p95 and about 274 MiB steady working set.
10. Add the five members' contribution statements and rehearse the prepared
    multi-turn demo before submission.

## Other possible implementations

Adopt these only when a measured failure justifies them:

- MiniLM product embeddings with exact NumPy search for vocabulary mismatch;
- a Top-N cross-encoder when candidate recall is high but MRR is low;
- a catalog-derived attribute graph for controlled query expansion;
- lightweight learning-to-rank for fusion after target-disjoint validation;
- Bayesian or simulated list-utility question selection;
- maximal marginal relevance for overly repetitive Browsing results;
- a local instruction model for structured intent hypotheses.

An external vector database, full-model training, multimodal retrieval, identity
reconstruction, and transaction handling remain unnecessary or out of scope.
