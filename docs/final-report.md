# Shopping Copilot MVP — Final Refinement Report

## Outcome

The current branch contains a working, offline-first conversational product
retriever that follows the official `starter.agent.Agent` contract. It returns
valid frozen-catalog IDs on every usable turn, asks at most one structured
question, maintains session state, handles intent corrections, and continues
without an LLM or network.

Public development-set result from the unmodified evaluator:

| Metric | Starter | Current MVP |
|---|---:|---:|
| Hit Rate@10 | 0.125 | 0.995 |
| MRR | 0.068 | 0.636 |
| MTTC | 9.81 | 2.245 |
| TechnicalScore | 0.107 | 0.8633 |

This is a public-set engineering result, not an estimate of the 800 private
sessions. One of 200 public targets remains unfound.

## Implemented product

1. The catalog is loaded into immutable product records and a field-aware
   in-memory SQLite FTS5 index.
2. Deterministic interpretation separates category, constraints, exclusions,
   numeric budget language, corrections, and no-preference replies. Raw catalog
   phrases remain available when normalization is unsafe.
3. A contextual reply resolver grounds short answers using explicit current
   evidence first and the immediately preceding Clarification second. Each slot
   update records explicit, contextual, or fallback provenance.
4. An optional billed semantic path adds anchored query rewrites and grounded
   soft feature/style/use-case hints. A call cap, cache, local validation, and
   deterministic fallback bound its risk.
5. Active State stores only currently valid session evidence; the anonymized
   profile is a capped soft prior.
6. Five lexical rank lists cover field relevance, title relevance, focused
   constraints, category relevance, and category-conditioned popularity.
7. Weighted Reciprocal Rank Fusion creates a bounded union. The full union is
   reranked by RRF support, IDF coverage, exact phrase coverage, capped rating
   volume, profile overlap, exclusions, and missing-neutral price bounds.
8. Previously shown products move behind unseen alternatives after rejection.
   Exposure resets on Intent Override.
9. Clarification uses top-candidate coverage and diversity. After an unanswered
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

Local Windows measurements on a 40-request broad-query audit:

- catalog startup: 2.45 s;
- mean response: 230 ms;
- p95 response: 265 ms;
- maximum response: 269 ms;
- steady process working set after load and one response: about 274 MiB.

These meet the provisional 500 ms / 500 MiB reliable-path budgets locally, but
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
- Subjective needs can receive LLM rewrites, but only anchored rewrites and
  grounded soft slots reach retrieval. Unsupported inferences are discarded and
  the deterministic path remains complete.

## Findings and trade-offs

The largest gains came from stateful clarification, capped popularity, category
coverage, unseen-first exposure, and reranking the complete bounded union. A
category-popularity route improved recall and time-to-hit but initially reduced
MRR, demonstrating that coverage and first-list precision must be tuned jointly.

Three rejected experiments are important:

- exposure without reset collapsed Override performance because feedback under
  the old intent was treated as permanent;
- treating every catalog phrase beginning with `no` as an exclusion reversed
  features such as `No Closure` and reduced TechnicalScore to 0.8588.
- spaCy with a small trained English model added substantial footprint and
  generic syntax but did not resolve shopping-specific short-answer semantics;
  it was tested locally, documented, and removed.

The first live LLM output also showed why grounding is necessary: it proposed
plausible category, material, and color values that were not explicitly stated.
Those slots were rejected while its two useful anchored rewrites were retained.

The remaining public miss is a low-volume novelty item in a large tie group.
Directly boosting it would overfit. A defensible next experiment is a
target-blind long-tail/diversity generator evaluated with target-ASIN-disjoint
folds.

## Before submission

1. Run the canonical unit tests and evaluator on the final judging machine.
2. Verify the catalog SHA-256 and keep `data/catalog.jsonl` out of Git.
3. Add all five team members' contribution statements.
4. Run a fixed real-language ambiguity corpus and obtain provider pricing before
   any further paid ablation. Require a measurable retrieval or parsing gain;
   the first 50-session paid sample produced no score delta.
5. Freeze configuration after target-disjoint validation; do not tune to the one
   remaining public ASIN.
6. Rehearse the two-turn demo described in [interaction-examples.md](interaction-examples.md).

Detailed experiments are in [findings.md](findings.md); prioritized work and
alternative implementations are in [todo.md](todo.md).
