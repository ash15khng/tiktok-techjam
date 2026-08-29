# MVP Findings

All scores below come from the unmodified public evaluator. Runtime code does not
read public labels, evaluator helpers, hidden intent cards, or ground truth.

## Results

| Run | Hit Rate@10 | MRR | MTTC | TechnicalScore |
|---|---:|---:|---:|---:|
| Published stateless BM25 | 0.125 | 0.068 | 9.81 | 0.107 |
| First conversational MVP | 0.865 | 0.558 | 3.86 | 0.743 |
| Selective override + capped popularity | 0.920 | 0.628 | 3.26 | 0.803 |

Final scenario results:

| Scenario | Hit Rate@10 | MRR | MTTC |
|---|---:|---:|---:|
| Buying | 0.938 | 0.589 | 2.54 |
| Browsing | 0.963 | 0.640 | 2.75 |
| Intent Override | 0.800 | 0.683 | 5.63 |
| Boundary | 0.800 | 0.670 | 6.00 |

Token usage is zero because the semantic provider is disabled.

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

## What did not work

- Stateless latest-message BM25 could not benefit from clarification replies.
- Clearing every preference on override discarded evidence that the customer had
  confirmed after the opening message.
- Pure relevance fusion left some metadata-identical targets below rank 10.
- Brand often looked discriminative in the candidate pool but was poorly
  answerable, so candidate partitioning needed an answerability prior.
- The current system still misses 20% of Override and Boundary sessions.

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
