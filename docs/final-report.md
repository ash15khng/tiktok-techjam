# Shopping Copilot MVP — Final Refinement Report

## Outcome

The current branch contains a working, offline-first conversational product
retriever that follows the official `starter.agent.Agent` contract. It returns
valid frozen-catalog IDs on every usable turn, asks at most one structured
question, maintains session state, handles intent corrections, and continues
without an LLM or network.

Historical complete-public development result from the unmodified evaluator:

| Metric | Starter | Current MVP |
|---|---:|---:|
| Hit Rate@10 | 0.125 | 0.995 |
| MRR | 0.068 | 0.636 |
| MTTC | 9.81 | 2.245 |
| TechnicalScore | 0.107 | 0.8633 |

This is a historical public-set engineering result, not an estimate of the 800
private sessions or the current tuning loop. New work uses a sealed 20% holdout
and four scenario-stratified, target/title-family-disjoint working folds. Their
locked 160-session score is `0.851762`; the holdout remains unopened.

## Implemented product

1. The catalog is loaded into immutable product records and a field-aware
   in-memory SQLite FTS5 index. One catalog-derived registry supplies supported
   attribute values, metadata priors, and log-quantile price bands.
2. Deterministic interpretation separates category, constraints, exclusions,
   numeric budget language, corrections, and no-preference replies. Raw catalog
   phrases remain available when normalization is unsafe.
3. A contextual reply resolver grounds short answers using explicit current
   evidence first and the immediately preceding Clarification second. Each slot
   update records explicit, contextual, or fallback provenance.
4. An optional billed semantic path adds anchored query rewrites and grounded
   soft feature/style/use-case hints. It runs only after deterministic retrieval
   shows a language/coverage concern. Eligibility uses parser fallback and
   sentence structure rather than a fixed adjective list. A call cap, cache, strict function tool,
   local validation, and deterministic fallback bound its risk.
5. Active State stores only currently valid session evidence; the anonymized
   profile is a capped soft prior.
6. Five lexical rank lists cover field relevance, title relevance, focused
   constraints, category relevance, and category-conditioned popularity.
7. Weighted Reciprocal Rank Fusion creates a bounded union. The full union is
   reranked by RRF support, IDF coverage, exact phrase coverage, capped rating
   volume, profile overlap, exclusions, and missing-neutral price bounds.
8. Previously shown products move behind unseen alternatives after rejection.
   Exposure resets on Intent Override.
9. Clarification uses top-candidate coverage, diversity, a catalog-derived
   prior, and session-specific answer/decline observations. After an unanswered
   field, one broad recovery question lets the customer volunteer a priority.
10. `ResponseGuard` removes invalid/duplicate IDs, caps the list at ten, and
   preserves valid output under component failure.

## Rule and scope review

| Requirement | Status |
|---|---|
| Frozen catalog and exact `parent_asin` | Compliant; source records are read-only |
| Maximum ten turns / Top 10 | Compliant through the official interface and guard |
| One allowed `ask_attribute` or null | Compliant and contract-tested |
| Buying, Browsing, Override, Boundary | Scenario results reported; no runtime scenario labels used |
| No hidden labels or evaluator access | Compliant; protected files are unchanged and runtime imports no evaluator code |
| Safe anonymized profile use | Capped soft term overlap only; no identity reconstruction |
| No catalog modification or external IDs | Compliant |
| No infrastructure-heavy vector database | Compliant; SQLite FTS5 only |
| Secrets and optional services | `.env` ignored; offline behavior is the default |

## Model, cost, and feasibility

The canonical 200-session score uses no model API: reported tokens are zero and
marginal API cost is $0. A locally validated SoCLaaS Responses-compatible
adapter is implemented but disabled unless an enable flag, API key, HTTPS base
URL, and explicit model are all supplied.

One live `llama3.1:8b` compatibility response succeeded in about 4.2 seconds and
reported 343 input plus 158 output tokens. Two preceding attempts exposed one
shape deviation and one 4-second timeout.

A paired, seeded 50-session public-set ablation then allowed at most two billed
calls. One succeeded, one failed safely, and 437 tokens were reported. LLM-off
and LLM-on produced the same `1.000` Hit Rate@10, `0.710802` MRR, `2.06` MTTC,
and `0.892041` TechnicalScore, with no session-level rank or hit-turn changes.
This supports the safety and cost controls but not enabling paid semantics for
the competition score. Provider pricing was not supplied, so monetary cost,
reliability, and p95 are not claimed.

A separate 14-case natural-language suite uses catalog targets outside the
public 200. The deterministic system scores `0.857143` Hit Rate, while an offline
ideal-rewrite provider reaches `1.000`, showing a real semantic-expansion
opportunity. Two four-call live passes produced no accepted hints and no metric
change; five calls completed, three failed, and 3,385 tokens were reported across
completed responses. The subsequent forced function-tool contract is mocked but
not live-validated.

The original pre-registry Windows audit measured 2.45 s startup and 265 ms p95.
The current 40-request first-turn audit measured:

- catalog startup: 7.81 s;
- mean response: 315 ms;
- p95 response: 574 ms;
- maximum response: 647 ms.

Cold start remains below the provisional 10-second target; p95 is now about
74 ms above the provisional 500 ms target. A prefix-pruned attribute matcher
reduced matching work without changing its reference output, but profiles show
the remaining slow path is mainly SQLite retrieval and full-union reranking.
Depth reductions require a candidate-recall ablation. Memory and all timings
must be repeated on the organizer's machine.

## User-interaction considerations

- Ask-and-recommend is retained because every turn is a chance to hit while the
  next question improves later turns.
- A declined attribute is suppressed; the agent does not repeatedly pressure
  the customer for it or reconstruct it from profile data.
- Compound requests such as `under $60, preferably red, no leather` are handled
  end to end. Missing price remains unknown rather than over budget.
- Corrections replace stale evidence before retrieval. Category remains stable
  unless the customer explicitly changes it.
- Short replies such as `Nike`, `7`, `80`, `blue/`, and bare `no` are grounded
  by the last Clarification without overriding explicit current evidence.
- Attribute values are catalog-derived rather than copied into material, color,
  size, style, brand, or use-case regex lists. Missing values stay unknown.
- Subjective needs can receive LLM rewrites, but only anchored rewrites and
  grounded soft slots reach retrieval. Unsupported inferences are discarded and
  the deterministic path remains complete.

## Findings and trade-offs

The largest gains came from stateful clarification, capped popularity, category
coverage, unseen-first exposure, and reranking the complete bounded union. A
category-popularity route improved recall and time-to-hit but initially reduced
MRR, demonstrating that coverage and first-list precision must be tuned jointly.

Four rejected experiments are important:

- exposure without reset collapsed Override performance because feedback under
  the old intent was treated as permanent;
- treating every catalog phrase beginning with `no` as an exclusion reversed
  features such as `No Closure` and reduced TechnicalScore to 0.8588.
- spaCy with a small trained English model added substantial footprint and
  generic syntax but did not resolve shopping-specific short-answer semantics;
  it was tested locally, documented, and removed.
- a separate typed-attribute candidate generator lowered working-fold score
  from `0.851762` to `0.836906`; a structured-evidence reranker scored
  `0.844619`. Both duplicated existing constraint evidence and added latency,
  so neither remains in runtime code.

The first live LLM output also showed why grounding is necessary: it proposed
plausible category, material, and color values that were not explicitly stated.
Those slots were rejected while its two useful anchored rewrites were retained.

The remaining historical public miss is a low-volume novelty item in a large tie group.
Directly boosting it would overfit. A defensible next experiment is a
   target-blind long-tail/diversity generator evaluated with the working folds.

## Before submission

1. Run the canonical unit tests and evaluator on the final judging machine.
2. Verify the catalog SHA-256 and keep `data/catalog.jsonl` out of Git.
3. Add all five team members' contribution statements.
4. Obtain provider pricing and validate the new forced function-tool request with
   one capped smoke call before any further paid suite. Keep semantics disabled
   by default until a live run accepts grounded hints and improves a hard case.
5. Freeze configuration, evaluate the sealed holdout once, then perform one
   complete-public compatibility replay. Do not tune after the holdout result or
   to the one remaining historical public ASIN.
6. Rehearse the two-turn demo described in [interaction-examples.md](interaction-examples.md).

Detailed experiments are in [findings.md](findings.md); prioritized work and
alternative implementations are in [todo.md](todo.md).
