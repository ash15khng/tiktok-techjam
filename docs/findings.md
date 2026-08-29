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

Final scenario results:

| Scenario | Hit Rate@10 | MRR | MTTC |
|---|---:|---:|---:|
| Buying | 0.975 | 0.614 | 2.19 |
| Browsing | 0.988 | 0.656 | 2.51 |
| Intent Override | 0.900 | 0.760 | 4.83 |
| Boundary | 0.800 | 0.531 | 5.80 |

Token usage is zero because the semantic provider is disabled.

The optional OpenAI Responses API adapter is contract-tested with mocked HTTP
responses only. It is not part of the reported score and has no measured cost or
latency yet.

## What worked

- Preserving raw disclosed constraints made long catalog feature text searchable.
- Active State let later answers refine retrieval without concatenating stale chat.
- Asking and recommending together preserved an immediate hit opportunity.
- `feature` was a strong first specific question; `other` remained a broad fallback.
- Four cheap lexical views improved recall without external infrastructure.
- Selective override removal retained later confirmed evidence.
- `rating_number` was useful as a capped tie-break: public targets have median
  rating count 6,846 while the full catalog median is 12.
- The response guard produced only valid, unique frozen-catalog identifiers.
- Moving already-shown products behind unseen candidates improved across-turn
  coverage without changing candidate scores.
- Resetting exposure on Intent Override restored products rejected under the old
  need and raised Override Hit Rate from 0.067 to 0.900.

## What did not work

- Stateless latest-message BM25 could not benefit from clarification replies.
- Clearing every preference on override discarded evidence that the customer had
  confirmed after the opening message.
- Pure relevance fusion left some metadata-identical targets below rank 10.
- Brand often looked discriminative in the candidate pool but was poorly
  answerable, so candidate partitioning needed an answerability prior.
- The current system still misses 10% of Override and 20% of Boundary sessions.
- Treating Recommendation Exposure as permanent caused a severe Override
  regression because the evaluator may reveal the corrected intent after a
  target appeared under the old intent.
- Boundary remains the weakest slice at 0.800 Hit Rate and needs a larger test set
  before scenario-specific tuning.

## Feasibility

A local 40-request audit measured:

- catalog startup: 2.37 seconds;
- mean response: 382 ms;
- p95 response: 470 ms;
- maximum response: 479 ms.

The p95 meets the initial 500 ms budget but has little headroom. Candidate depth
and rerank depth should be tuned jointly with recall rather than reduced blindly.

## Caveats

The public set has only 200 sessions. Current numeric weights are engineering
guesses informed by public diagnostics and need target-ASIN-disjoint validation.
No private-set performance, LLM quality, production user impact, or external API
reliability is claimed.
