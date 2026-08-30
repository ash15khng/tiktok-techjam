# Implementation Findings

All scores below come from the unmodified public evaluator. Runtime code does not
read public labels, evaluator helpers, hidden intent cards, or ground truth.

## Results

The current generalized code was replayed on all 200 public sessions after the
package/configuration refactor. It scored Hit Rate `0.990`, MRR `0.617232`, MTTC
`2.550`, and TechnicalScore `0.849170`. A replay of the immediate parent commit
produced the same aggregate metrics and zero session-level hit-turn/rank
differences. The table below is the historical experiment trail; its peak is not
the current submission result.

Current generalized scenario results:

| Scenario | Hit Rate@10 | MRR | MTTC |
|---|---:|---:|---:|
| Buying | 0.987500 | 0.594678 | 1.925000 |
| Browsing | 1.000000 | 0.591478 | 2.512500 |
| Intent Override | 0.966667 | 0.661799 | 4.266667 |
| Boundary | 1.000000 | 0.870000 | 2.700000 |

Historical experiment trail:

| Run | Hit Rate@10 | MRR | MTTC | TechnicalScore |
|---|---:|---:|---:|---:|
| Published stateless BM25 | 0.125 | 0.068 | 9.81 | 0.107 |
| First conversational prototype | 0.865 | 0.558 | 3.86 | 0.743 |
| Selective override + capped popularity | 0.920 | 0.628 | 3.26 | 0.803 |
| Unseen-first, without override reset | 0.835 | 0.538 | 3.76 | 0.724 |
| Unseen-first, reset on override | 0.960 | 0.648 | 2.895 | 0.837 |
| Category-conditioned popularity route | 0.985 | 0.629 | 2.385 | 0.854 |
| Rerank depth 320 | 0.985 | 0.626 | 2.365 | 0.853 |
| Broad recovery after unanswered field | 0.985 | 0.641 | 2.300 | 0.859 |
| Broad recovery + full-union rerank | 0.995 | 0.635 | 2.245 | 0.863 |
| Compound user parsing + price signal | 0.995 | 0.635 | 2.245 | 0.863 |
| Contextual reply resolver | 0.995 | 0.636 | 2.245 | 0.8633 |

Historical peak scenario results:

| Scenario | Hit Rate@10 | MRR | MTTC |
|---|---:|---:|---:|
| Buying | 0.988 | 0.622 | 1.78 |
| Browsing | 1.000 | 0.596 | 2.03 |
| Intent Override | 1.000 | 0.754 | 3.87 |
| Boundary | 1.000 | 0.703 | 3.00 |

Token usage is zero because the semantic provider is disabled.

The optional SoCLaaS Responses-compatible adapter is not part of the reported
score. A no-network public replay found 13 eligible calls and 12 unique
message/context pairs. Three live compatibility requests were attempted: one
initial shape rejection, one 4-second timeout, and one success in about 4.2
seconds using 343 input and 158 output tokens. Provider pricing was not supplied,
so monetary cost is not claimed. This sample is too small for a latency or
quality distribution.

### Seeded 50-session semantic ablation

On 2026-08-29, a paired evaluation sampled 50 of the 200 public sessions with
seed `20260829`. Both arms used the same sample IDs and the unmodified evaluator.
The LLM-off control and LLM-on arm produced identical results:

| Arm | Hit Rate@10 | MRR | MTTC | TechnicalScore | Provider attempts | Reported tokens |
|---|---:|---:|---:|---:|---:|---:|
| LLM off | 1.000 | 0.710802 | 2.06 | 0.892041 | 0 | 0 |
| LLM on, cap 2 | 1.000 | 0.710802 | 2.06 | 0.892041 | 2 | 437 |

The random sample contained 25 Buying, 16 Browsing, 5 Boundary, and 4 Intent
Override sessions. The language gate skipped 101 interpreter turns and selected
two messages: one mixed an everyday-bra request with a catalog date field, and
one described lightweight, responsive walking-shoe cushioning. These are
plausible noise-removal and subjective-language cases, but the deterministic
retriever already solved both trajectories. One provider request succeeded,
one failed safely, and all 50 session-level hit turns and ranks were unchanged.

This run validates the spending controls and fallback, not LLM value. The
sample provides no evidence that paid semantics improves the competition score,
so the provider remains off by default. Further paid testing should first pass
a fixed offline ambiguity corpus and should add retrieval uncertainty to the
language gate. Provider pricing is still unavailable, so only calls and tokens,
not currency cost, are reported. Local ignored result files use the `E013`
prefix under `artifacts/results/`.

### Natural-language stress suite and two-pass semantics

A separate frozen suite uses 14 manually written conversations whose targets
are absent from the public 200. The deterministic system scores Hit Rate
`0.857143`, MRR `0.7375`, and MTTC `1.357143`. Its two misses are an implicit
lightweight windbreaker request and a comfort-metaphor house-slipper request.

An offline ideal-rewrite provider recovers both at rank 5, raising Hit Rate to
`1.000`, MRR to `0.766071`, and lowering MTTC to `1.071429`. This is an upper
bound, not a model result, but it proves that grounded query expansion can help
the existing candidate and reranking pipeline.

The implementation now parses and retrieves deterministically before deciding
whether to call the provider. It selected zero calls on the previous seeded
50-session sample and 4 of 15 turns on the hard suite. Exact leading-product
evidence suppresses unnecessary calls. Semantic evidence is applied without
advancing the turn, and retrieval repeats only when accepted evidence changes
state. At that pre-generalization checkpoint, the full 200-session LLM-off
score remained exactly `0.863324`.

Two capped live hard-suite passes made eight attempts total. Five completed,
three failed, and completed outputs produced no locally usable hints. The first
run reported 1,258 tokens and the example-guided run reported 2,127. Both had
zero score and session-rank delta. A forced strict function-tool response is now
implemented and mocked, but has not been live-validated. Provider price remains
unknown, so currency cost is not reported.

### Final compound-turn and semantic-state pass

The following natural conversation exposed three deterministic defects:

```text
im looking for red shoes
size 10
no budget, actually make the shoes black
for casual wear, actually i want it dont care about colour too
```

Previously, `no budget` became an exclusion, the last message became a false
category, and size/casual-wear evidence was lost. The retained behavior now ends
with category `shoes`, size `size 10`, use case `casual wear`, and both budget and
color marked unrestricted. Red and black are absent from final query terms. This
trajectory is covered end to end.

An initial general catalog-modifier splitter repaired that example but reduced
the independent hard suite from HR `0.857143`, MRR `0.7375` to HR `0.785714`,
MRR `0.608929`. It over-segmented long natural product phrases. Restricting this
behavior to correction time—removing a stale catalog-linked color only from a
compact category phrase—restored the hard suite exactly to HR `0.857143`, MRR
`0.7375`, MTTC `1.357143`. The full public LLM-off evaluation also remained
exactly HR `0.99`, MRR `0.617232`, MTTC `2.55`, and TechnicalScore `0.84917`.

The semantic contract now receives structured Active State and supports all
competition fields with `add`, `replace`, `exclude`, and `set_any`. A preflight
gate handles compound/unresolved turns before mutation; the retrieval-aware gate
is used only if preflight skipped. Rewrites are isolated from durable customer
facts, so later corrections can invalidate them safely. One capped smoke command
found the local provider disabled/incomplete and made no HTTP request.

## What worked

- Preserving raw disclosed constraints made long catalog feature text searchable.
- Active State let later answers refine retrieval without concatenating stale chat.
- Asking and recommending together preserved an immediate hit opportunity.
- `feature` was a strong first specific question; `other` remained a broad fallback.
- Five cheap lexical rank lists improved recall without external infrastructure.
- Selective override removal retained later confirmed evidence.
- `rating_number` was useful as a capped tie-break: public targets have median
  rating count 6,846 while the full catalog median is 12.
- The response guard produced only valid, unique frozen-catalog identifiers.
- Moving already-shown products behind unseen candidates improved across-turn
  coverage without changing candidate scores.
- Resetting exposure on Intent Override restored products rejected under the old
  need and raised Override Hit Rate from 0.067 to 0.900.
- Ranking a deeper category pool separately by rating count recovered broad-query
  targets that category BM25 lost in large tie groups. It increased Hit Rate to
  0.985 and reduced MTTC to 2.385 without a model or private information.
- Asking one broad recovery question after an unanswered field raised MRR and
  recovered the last Override miss; it also avoids a field-by-field interview.
- Reranking the complete bounded candidate union recovered constraint-matching
  products below the former rank-160 cutoff, bringing Boundary and Override to
  1.000 Hit Rate on the small public slices.
- Provenance-aware negation preserved catalog phrases such as `No Closure`
  while supporting direct user exclusions such as `no leather`.
- Compound user parsing and missing-neutral numeric price scoring passed an
  end-to-end synthetic interaction without changing the public metrics.
- Immediate-question context correctly grounds brands, numeric sizes, bare
  budgets, categories, and declines while explicit current evidence retains
  priority. It slightly improved overall MRR without changing Hit Rate or MTTC.
- The live model produced useful anchored rewrites for a subjective shopping
  request. A local grounder retained those rewrites while rejecting unsupported
  category, material, and color inferences before they reached retrieval.
- A hard process call cap, successful-result cache, and zero-token cache-hit
  accounting bound paid usage without weakening the offline fallback.
- The paired 50-session run spent only two provider attempts out of 103 parsed
  turns and degraded no session when one request failed.
- Retrieval-aware escalation removed both paid calls from that saturated sample
  while an offline rewrite oracle recovered both independent hard-suite misses.

## What did not work

- Stateless latest-message BM25 could not benefit from clarification replies.
- Clearing every preference on override discarded evidence that the customer had
  confirmed after the opening message.
- Pure relevance fusion left some metadata-identical targets below rank 10.
- Brand often looked discriminative in the candidate pool but was poorly
  answerable, so candidate partitioning needed an answerability prior.
- Category popularity traded some first-list precision for coverage: MRR fell
  from 0.648 to 0.629 even while the total TechnicalScore improved.
- Reranking 320 instead of 160 candidates did not reach the deeper constraint
  matches and slightly reduced TechnicalScore; the useful cutoff was the full
  bounded union in this implementation.
- One public Buying session still misses. Its low-volume novelty T-shirt remains
  below rank 160 before extra constraints and below rank 350 afterward; forcing
  it upward would require a general long-tail coverage method, not target tuning.
- Treating every `no ...` catalog phrase as an exclusion reduced TechnicalScore
  to 0.8588. The fix was to distinguish catalog-shaped payload evidence from
  direct customer clauses rather than weakening exclusions globally.
- Treating Recommendation Exposure as permanent caused a severe Override
  regression because the evaluator may reveal the corrected intent after a
  target appeared under the old intent.
- Boundary has only ten public sessions. Its final 1.000 Hit Rate and high MRR
  are encouraging but too small a slice for scenario-specific confidence.
- spaCy 3.8.7 with `en_core_web_sm` was not retained. The local probe added
  about 226 MiB on disk, 119 MiB standalone working memory, 1.0 s startup, and
  4.75 ms per message. It exposed useful syntax but did not ground shopping
  attributes: `7` and `80` remained generic cardinals and `blue/` was tagged as
  a number. The deterministic resolver took about 4 microseconds per message.
- The first live LLM response deviated from the requested list limits, and a
  second request exceeded the original 4-second timeout. Bounded tolerant
  parsing and a provisional 6-second timeout addressed compatibility, but the
  gateway still needs a larger reliability and p95 sample.
- The sampled semantic ablation consumed 437 tokens without changing any scored
  session. Language complexity alone is therefore not a sufficient economic
  gate when deterministic retrieval is already confident.
- Adding rewrite examples to the 8B text prompt increased reported input tokens
  but still yielded no accepted hint. Prompt prose alone was not a reliable
  output contract; the adapter now uses a forced strict function tool.

## Feasibility

A historical local 40-request audit before the catalog-attribute registry measured:

- catalog startup: 2.45 seconds;
- mean response: 230 ms;
- p95 response: 265 ms;
- maximum response: 269 ms.
- steady process working set after one response: 274 MiB.

Those figures are retained as the pre-registry reference. Current measurements
are recorded in the re-engineering section below; this is not an end-to-end
judging-machine guarantee.

## 2026-08-30 generalization and split review

The scattered material/color/size/use-case word lists and fixed `$25` price
buckets were removed. The fixed API attribute names remain because they are the
organizer contract. Their values now come from one catalog-derived registry.

Catalog observations:

- 279 distinct structured detail keys exist;
- title and category are present for all 50,000 products;
- features cover 89.6%, details 96.7%, store 99.4%, description 52.2%, and
  valid positive price only 21.1%;
- direct typed keys are sparse: material 2,069 products, color 2,439, style
  1,752, size 925, sport 260, and occasion 215;
- catalog price quantiles are approximately `$9.99`, `$14.99`, `$22.88`,
  `$39.99`, and `$80.00`, so a fixed `$25` partition was poorly matched to the
  skewed distribution.

Consequences:

- missing fields stay unknown in retrieval, reranking, and questioning;
- no product is rejected merely because an attribute or price is absent;
- catalog-native values can be resolved without editing source lists;
- package dimensions are excluded from wearable-size evidence;
- exact normalized phrases are preferred; fuzzy linking is not implemented;
- the optional LLM is still needed for true open-world paraphrase, metaphor,
  misspelling, and implicit-need translation.

Clarification now starts from an O(1) prior derived from catalog coverage and
repeated-value support. Per-session answers, declines, and redirects update a
Beta-style posterior for the remaining questions, and `reset()` clears it. The
one-time `other` recovery remains because catalog attributes do not capture every
customer priority.

The public set was split into a 40-session release partition and four 40-session
working folds. Exact normalized-title families cannot cross partitions and every
partition is scenario-stratified. The 160-session working-fold checkpoint is Hit
Rate `0.9875`, MRR `0.632125`, MTTC `2.58125`, and TechnicalScore `0.851762`.
The release partition was not opened during this tuning pass; it was later
included in the final full-public compatibility replay.

### Retrieval and ranking ablation

The retained implementation already produces five candidate lists—field,
title, category relevance, category popularity, and focused constraints—then
combines them with weighted RRF and reranks the bounded union. Two additional
attribute-aware mechanisms were evaluated and rejected:

| Development variant | Hit Rate | MRR | MTTC | Score | Decision |
|---|---:|---:|---:|---:|---|
| Retained five-route system | 0.9875 | 0.632125 | 2.58125 | 0.851762 | Keep |
| Typed-attribute route only | 0.9750 | 0.612187 | 2.71250 | 0.836906 | Reject |
| Structured support reranker only | 0.9750 | 0.635813 | 2.68125 | 0.844619 | Reject |
| Both additions | 0.9750 | 0.624472 | 2.71875 | 0.840467 | Reject |

The new route duplicated terms already present in the constraint generator and
diffused RRF/exposure ordering. The structured scorer recovered small MRR in a
few Buying cases but reduced Hit Rate and Intent Override reliability, and its
product-value inference substantially increased latency. Neither path remains in
runtime code.

The frozen 14-case consumer-language suite initially kept the same Hit Rate but
moved one natural intent-correction target from rank 1 to rank 2. Adding general
`make that <category> with <constraint>` operation parsing restored the previous
Hit Rate `0.857143`, MRR `0.7375`, and MTTC `1.357143`. No fixture ASIN or product
term was added to runtime logic.

The optional semantic gate also no longer enumerates adjectives such as
`comfortable`, `formal`, or `lightweight`. It now escalates substantive turns
from parser fallback provenance, implicit outcome/reason constructions, missing
or ambiguous category evidence, and low retrieval stability. Minimum message
length, exact-top-evidence suppression, the process call cap, cache, and local
grounding still bound billed use. Because this changes eligibility, the older
13-call dry-run estimate must be rerun before any paid suite.

Prefix-pruned attribute inference reduced repeated value-matching work. A
2,000-product equivalence audit found zero output differences from the reference
longest-first scan after punctuation-sensitive semantics were preserved. Final
local measurements were 7.81 s startup, 315 ms mean response, 574 ms p95, and
647 ms maximum over 40 deterministic first turns. Cold start remains under the
10 s target, but p95 exceeds the provisional 500 ms budget. These figures should
be rerun on the judging machine; profiling shows the long-tail response cost is
now dominated by SQLite retrieval and full-union reranking rather than
clarification lookup.

## Caveats

The public set has only 200 sessions. Current numeric weights are engineering
guesses; repeated working-fold choices can still overfit despite target-family
grouping. The 20% release partition was held out until configuration freeze and
has since been included in the final compatibility replay, so only the organizer's
800 sessions are truly unseen. No private-set performance, LLM score gain,
production user impact, provider cost, or external API reliability is claimed.
