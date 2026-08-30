# Engineering TODO and Alternatives

## Prioritized work

1. Measure target recall at depths 10, 50, 100, 160, and the complete candidate
   union for each retained route. Report marginal recall, not only final score.
2. Design a genuinely complementary long-tail generator. Do not re-add the
   rejected typed-attribute route or tune directly to a missed ASIN.
3. Improve first-turn MRR beyond the retained `0.669479` working-fold result
   without regressing Hit Rate `0.9875`, MTTC `2.58125`, or any scenario without
   an explicit tradeoff.
4. Tune route weights, rerank weights, popularity cap, question threshold, and
   candidate depth only through the four working folds.
5. Add explicit tri-state constraint evidence: match, contradiction, or unknown.
6. Add configuration hashes and optional per-turn traces without hidden labels.
   Existing aggregate diagnostics intentionally omit messages, profiles, and IDs.
7. Live-validate the forced semantic function tool with one capped smoke call.
   Do not run another paid suite unless it returns at least one grounded rewrite.
8. Expand the frozen 14-case suite with independently reviewed natural language,
   especially competing constraints, terse implicit needs, and multi-turn
   corrections. Keep all targets outside the public 200.
9. Record pre/post candidate ranks and accepted hints per semantic call without
   storing credentials or raw provider responses.
10. Grow the current 92-test suite to at least 100 parser utterances, especially
   conjunction scope, short sizes, brand aliases, typos, and contextual replies
   that explicitly switch attributes.
11. Reduce catalog-registry cold start and rerun latency/memory on the judging
   environment. Do not reduce candidate depth without a recall ablation.
12. Rehearse the release from a clean checkout and verify catalog checksum,
   environment setup, startup time, evaluator output, and credential hygiene.
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

Measured but disabled/rejected options should be reconsidered only with new
target-disjoint evidence:

- exact-phrase rarity ordering is implemented at zero weight; its catalog-pool
  scans cost more and did not beat the simpler retained ordering;
- profile-only final ordering caused small Boundary/Browsing regressions;
- popularity weight `0.10` raised aggregate MRR but regressed Boundary, so the
  retained `0.05` is a deliberately conservative tie-break;
- candidate-viable clarification filtering needs explicit match/contradiction/
  unknown evidence before it can safely discard a question;
- dense retrieval should be adopted only if it adds candidate recall beyond the
  five lexical routes within startup, memory, and response-latency budgets; and
- an expected-value action policy needs target-disjoint conversation simulation
  before it replaces the current ask-and-recommend rule.

An external vector database, full-model training, multimodal retrieval, identity
reconstruction, and transaction handling remain unnecessary or out of scope.

## Adoption gates for a new NLP component

Before adding a trained NLP model or linker, require:

1. parser-corpus improvement beyond deterministic context and catalog aliases;
2. no material regression in working-fold or target-disjoint metrics;
3. acceptable cold-start, p95 latency, memory, and install footprint;
4. deterministic fallback when the model or asset is absent; and
5. explicit setup, dependency, model, cost, and limitation disclosure.
