# MVP Findings

All scores below come from the unmodified public evaluator. Runtime code does not
read public labels, evaluator helpers, hidden intent cards, or ground truth.

## Results

| Run | Hit Rate@10 | MRR | MTTC | TechnicalScore |
|---|---:|---:|---:|---:|
| Published stateless BM25 | 0.125 | 0.068 | 9.81 | 0.107 |
| First conversational MVP | 0.865 | 0.558 | 3.86 | 0.743 |
| Selective override + capped popularity | 0.920 | 0.628 | 3.26 | 0.803 |
| Unseen-first, without override reset | 0.835 | 0.538 | 3.76 | 0.724 |
| Unseen-first, reset on override | 0.960 | 0.648 | 2.895 | 0.837 |
| Category-conditioned popularity route | 0.985 | 0.629 | 2.385 | 0.854 |
| Rerank depth 320 | 0.985 | 0.626 | 2.365 | 0.853 |
| Broad recovery after unanswered field | 0.985 | 0.641 | 2.300 | 0.859 |
| Broad recovery + full-union rerank | 0.995 | 0.635 | 2.245 | 0.863 |
| Compound user parsing + price signal | 0.995 | 0.635 | 2.245 | 0.863 |
| Contextual reply resolver | 0.995 | 0.636 | 2.245 | 0.8633 |

Final scenario results:

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

## Feasibility

A local 40-request audit measured:

- catalog startup: 2.45 seconds;
- mean response: 230 ms;
- p95 response: 265 ms;
- maximum response: 269 ms.
- steady process working set after one response: 274 MiB.

The p95 meets the initial 500 ms reliable-path budget in this local broad-query
audit. This is not an end-to-end judging-machine guarantee; candidate depth and
rerank depth still need joint recall/latency tuning.

## Caveats

The public set has only 200 sessions. Current numeric weights are engineering
guesses informed by public diagnostics and need target-ASIN-disjoint validation.
No private-set performance, LLM score gain, production user impact, provider
cost, or external API reliability is claimed.
