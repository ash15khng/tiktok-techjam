# Engineering TODO and Alternatives

## Prioritized work

1. Measure target recall at depths 10, 50, 100, 160, and the complete candidate
   union for each retained route. Report marginal recall, not only final score.
2. Design a genuinely complementary long-tail generator. Do not re-add the
   rejected typed-attribute route or tune directly to a missed ASIN.
3. Improve first-turn MRR without regressing the locked working-fold Hit Rate
   `0.9875`, MTTC `2.58125`, or any scenario without an explicit tradeoff.
4. Tune route weights, rerank weights, popularity cap, question threshold, and
   candidate depth only through the four working folds.
5. Add explicit tri-state constraint evidence: match, contradiction, or unknown.
6. Add configuration hashes and optional per-turn traces without hidden labels.
7. Live-validate the forced semantic function tool with one capped smoke call.
   Do not run another paid suite unless it returns at least one grounded rewrite.
8. Expand the frozen 14-case suite with independently reviewed natural language,
   especially competing constraints, terse implicit needs, and multi-turn
   corrections. Keep all targets outside the public 200.
9. Record pre/post candidate ranks and accepted hints per semantic call without
   storing credentials or raw provider responses.
10. Grow the current 77-test suite to at least 100 parser utterances, especially
   conjunction scope, short sizes, brand aliases, typos, and contextual replies
   that explicitly switch attributes.
11. Reduce catalog-registry cold start and rerun latency/memory on the judging
   environment. Do not reduce candidate depth without a recall ablation.
12. Freeze configuration, open the 40-session holdout once, then perform one
   final complete-public compatibility replay. Do not tune after holdout review.
13. Add the five members' contribution statements and rehearse the prepared
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

## Adoption gates for a new NLP component

Before adding a trained NLP model or linker, require:

1. parser-corpus improvement beyond deterministic context and catalog aliases;
2. no material regression in working-fold or target-disjoint metrics;
3. acceptable cold-start, p95 latency, memory, and install footprint;
4. deterministic fallback when the model or asset is absent; and
5. explicit setup, dependency, model, cost, and limitation disclosure.
