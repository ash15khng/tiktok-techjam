# Natural-Language Stress Evaluation

The official evaluator remains the score regression gate. This separate suite
tests language patterns that the public simulator may not represent.

## Dataset boundary

`tests/stress/hard_cases.json` was frozen before its first score was observed.
Its target products exist in the frozen catalog but are absent from all 200
public targets. The 14 cases cover implicit needs, misspellings,
subjective product language, conjunctions, multi-turn refinement, and intent
override. They are manually written rather than copied from catalog fields.

This is a product stress test, not an estimate of the private-set score. It is
small and intentionally difficult. Do not rewrite a valid case merely because
the system misses it; fix only ambiguity, incorrect product evidence, or broken
fixture data and document the change.

Version 2 replaced the target in two related cases after the first run showed
that the original product had another parent record with effectively identical
title, features, price, and use cases. Exact-ASIN recovery was therefore not
identifiable from the customer language. No genuine retrieval miss was removed.

## Run

Run the deterministic benchmark without API calls:

```powershell
$env:SHOPPING_COPILOT_LLM_ENABLED = "0"
python -m tests.stress.hard_evaluator --output artifacts/results/hard-off.json
```

The CLI reports Hit Rate at the end of each scripted conversation, MRR, MTTC,
and token usage. Per-case turns and ranks are written to the optional ignored
artifact. Fixture validation runs with the ordinary test suite.

## Evaluation discipline

Every change must satisfy both gates:

1. the canonical public score must not fall below the recorded deterministic
   result;
2. hard-suite gains must come from a general mechanism, not a target ASIN or a
   case-specific rule.

For semantic experiments, first use a mocked or recorded provider. Live calls
require an explicit cap, no automatic retries, and a paired LLM-off comparison.
Record provider attempts, successful calls, failures, reported tokens, accepted
hints, candidate-rank deltas, and final session deltas.

## Current results

| System | Hit Rate | MRR | MTTC | Provider attempts |
|---|---:|---:|---:|---:|
| Deterministic | 0.857143 | 0.7375 | 1.357143 | 0 |
| Offline ideal rewrites | 1.000 | 0.766071 | 1.071429 | 4 simulated |
| Live text-output model | 0.857143 | 0.7375 | 1.357143 | 4 |
| Live example-guided text model | 0.857143 | 0.7375 | 1.357143 | 4 |

Both deterministic misses are recoverable at rank 5 when supplied with safe,
catalog-searchable rewrites. Across the two live runs, five requests completed,
three failed, and no hint survived local validation. The strict function-tool
revision that follows these runs is mocked but not live-validated.
