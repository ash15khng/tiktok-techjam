# Differentiation and Competitive Trade-offs

## Short answer

Shopping Copilot is not universally smaller, cheaper, or faster than every
catalog-local alternative. Its default path has zero API cost, the fastest
measured startup of the compared systems, middle-of-the-pack memory and warm
latency, and the lowest public score of the three measured implementations.
Its advantage is the combination of strong retrieval with a safer real-user
conversation model: typed corrections, missing-neutral constraints,
question-value selection, full Top-10 recommendations, bounded personalization,
and optional grounded semantics.

## Like-for-like local measurements

These figures were reproduced on the same Windows machine, frozen catalog, full
200-session public set, `top_k=10`, and model-free path. “Representative A/B”
denote independently implemented, publicly visible catalog-local approaches;
their source was inspected for behavior but no unlicensed code was copied.

| Measure | Shopping Copilot | Representative A | Representative B |
|---|---:|---:|---:|
| Hit Rate@10 | 0.995 | 0.995 | 1.000 |
| MRR | 0.667556 | 0.669435 | 0.748714 |
| MTTC | 2.335 | 1.950 | 1.530 |
| TechnicalScore | 0.871067 | 0.879331 | 0.914014 |
| Catalog startup | 9.35 s | 11.98 s | 15.78 s |
| Repeated-request mean | 27.61 ms | 1.47 ms | 42.97 ms |
| Repeated-request p95 | 51.03 ms | 3.31 ms | 72.87 ms |
| Working set after audit | 359.90 MiB | 478.13 MiB | 257.42 MiB |
| Default model/API cost | $0 | $0 | $0 |

The Shopping Copilot latency row includes the new bounded query cache. Its first
uncached request in that audit was `483.15 ms`, so `27.61 ms` is not a cold-turn
claim. The 14-case hard-language replay had zero search-cache hits across 70
unique FTS queries, while preserving its score; the cache therefore improves
repeated work, not semantic generalization. A full instrumented public replay
took `90.26 s` after `9.80 s` startup. Machine-local timings are directional,
not judging-host guarantees.

## Where this system is stronger

- **Faster initialization:** its FTS plus compact category buckets initialized
  sooner than both representative systems in the paired audit.
- **Controlled operating cost:** the canonical system is Python standard
  library plus SQLite FTS5, reports zero tokens, and requires no hosted model,
  GPU, embedding build, or infrastructure-heavy vector database.
- **Bounded memory mechanisms:** each product ID is stored once in the
  structural buckets; product token views and immutable FTS results use bounded,
  per-agent caches. It used about 25% less memory than A, though more than B.
- **Conversation correctness:** `add`, `replace`, `exclude`, and `set_any`
  operations update typed state with provenance. Size, budget, and use case
  survive an unrelated color correction; intent overrides clear stale semantic
  rewrites and exposure state.
- **Honest missing data:** absent material, price, size, or style is unknown—not
  a mismatch. This matters beyond the synthetic disclosure pattern.
- **Useful output every turn:** it returns a full ranked Top 10 while asking one
  high-value question, rather than optimizing the interaction around a
  single-item disclosure ladder.
- **Open-world escape hatch:** a strictly capped LLM can propose grounded field
  operations and semantic rewrites for difficult consumer language. It cannot
  emit ASINs or silently replace deterministic evidence.
- **Failure containment:** timeouts, invalid model output, duplicate turns, late
  turns, and component exceptions preserve a valid deterministic response.

## Where this system is weaker

- **Lower public score:** Representative B is `0.042947` higher in TechnicalScore
  and reaches targets roughly `0.805` turns earlier on average.
- **Cold response latency:** the six-route FTS/RRF/full-union reranker performs
  more work than a direct precomputed bucket lookup. Cache hits help repeated
  terms but do not eliminate unique-query cost.
- **Intermediate memory rather than minimum memory:** SQLite FTS, product
  records, the catalog-derived attribute registry, and two bounded caches cost
  about `359.9 MiB`; B used about `257.4 MiB`.
- **Conservative semantics:** strict grounding intentionally rejects guesses.
  Implicit needs, metaphors, misspellings, and cross-category language can still
  miss when the optional model is disabled.
- **Public-template mismatch:** direct category/disclosure policies align very
  closely with the released simulator. This system deliberately preserves
  natural Top-10 behavior and attribute-specific questions, so it does not copy
  every simulator-shaped shortcut.

## Why the score was lower, and what changed

The preceding system depended on fielded BM25 for candidate membership. That is
robust to noisy text but weak inside large product families, where many records
share the same category words. It also spent more turns learning a preference
before a low-volume target entered the union.

The retained structural route adds catalog-native family evidence without
removing FTS recall. An unrestricted version improved early hits but collapsed
working MRR, so it was gated on one positive preference phrase and reduced to
`0.80/0.50` RRF weight. Compared with the previous public checkpoint, it:

- raises Hit Rate from `0.990` to `0.995`;
- raises MRR from `0.657026` to `0.667556`;
- lowers MTTC from `2.550` to `2.335`; and
- raises TechnicalScore from `0.861108` to `0.871067`.

On the 160 working sessions it gained one hit, lost none, moved 19 hits earlier
and one later, improved 35 target ranks, and worsened 16. The independent
14-case language suite was exactly unchanged. These checks support the mechanism
but do not make the public set unseen; the organizer's 800 sessions remain the
only final generalization test.

## Next measured optimization targets

1. Profile category/title FTS and reranker scans on target-disjoint paraphrases;
   do not reduce candidate depth unless Hit Rate and MTTC remain non-regressive.
2. Evaluate a compact dense or sparse-semantic route as one additional candidate
   generator, with an explicit startup/memory/latency budget.
3. Calibrate the LLM gate on accepted state deltas per dollar and p95 latency,
   not on number of calls. Current live calls have no measured score gain.
4. Tune structural weights only on new target-family-disjoint data. The current
   public-selected values are frozen to avoid further overfitting.
