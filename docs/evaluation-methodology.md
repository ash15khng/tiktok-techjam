# Evaluation Methodology

The 200 labeled public sessions are development data, not a final test set. The
800 organizer sessions remain the only truly private evaluation. To reduce
public-set overfitting, local work uses three separate gates.

## Data roles

| Data | Role | May influence implementation? |
|---|---|---|
| Frozen 50,000-product catalog | Runtime input and unsupervised schema/statistics source | Yes; every judged agent receives it |
| 160 public development sessions | Repeated engineering and ablation | Yes |
| 40 public sealed-holdout sessions | One final local check after configuration freeze | No, until release candidate |
| 14 frozen hard-language cases | Product-language stress test; targets are outside the 200 public targets | Only through general fixes, never case/ASIN rules |
| 800 organizer-private sessions | Final judging | Never |

Using the complete frozen catalog to build FTS indexes, attribute vocabularies,
metadata coverage, and price quantiles is allowed and is not label leakage. The
runtime must not import the evaluator or read public labels, intent cards, or
ground truth.

## Split construction

`devtools.development_splits` creates a deterministic manifest with seed
`techjam-2026-v1`:

1. normalize each target product title;
2. group exact normalized-title families together, falling back to target ASIN;
3. reserve 20% as a sealed holdout;
4. split the remaining 80% into four scenario-stratified folds;
5. assert that neither a sample nor a target/title family crosses a partition.

The resulting local split is 40 sealed sessions plus four 40-session
development folds. Every partition has the expected 40/40/15/5 scenario mix:
16 Buying, 16 Browsing, 6 Intent Override, and 2 Boundary sessions per 40.

Generate the ignored manifest:

```powershell
python -m devtools.development_splits
```

The manifest contains sample IDs and grouping information, lives under
`.local/`, and is intentionally excluded from Git.

## How to tune without fooling ourselves

- Compare every material change on the same four development folds.
- Report the aggregate and every scenario, not only the best fold.
- If parameters are learned, fit on three folds and score the fourth, rotating
  the validation fold. Do not fit on the validation fold.
- Hand-selected constants are still capable of overfitting through repeated
  experiments. The sealed holdout protects against that selection process.
- Change one material variable per ablation. Retain it only when the gain is
  reproducible and latency remains acceptable.
- Do not open the sealed holdout to decide the next weight. Open it once after
  code and parameters are frozen; then do not tune again from that result.
- Run the complete 200-session evaluator only as the final compatibility and
  reporting replay, not after every edit.

Run the working-fold gate, which deliberately excludes the sealed holdout:

```powershell
$env:SHOPPING_COPILOT_LLM_ENABLED = "0"
python -m devtools.evaluate_development_folds
```

## Current locked checkpoint

The retained deterministic configuration scored the following on the 160
working sessions:

| Metric | Result |
|---|---:|
| Hit Rate@10 | 0.987500 |
| MRR | 0.632125 |
| MTTC | 2.581250 |
| Efficiency | 0.841875 |
| TechnicalScore | 0.851762 |

The 40-session holdout has not been evaluated during this re-engineering pass.
The older full-public score of `0.863324` remains a historical compatibility
reference, not the tuning target for these changes.

## Acceptance gates

A change is retained only when all applicable checks pass:

1. API contract and unit/integration tests;
2. no aggregate development-fold score regression, with scenario changes
   explained rather than hidden;
3. no generalization regression on the frozen hard-language suite;
4. deterministic fallback still works with the LLM disabled or unavailable;
5. latency/token cost is proportionate to the measured gain;
6. official evaluator, labels, catalog IDs, and source records remain unchanged.

The hard-language suite is not a private-score estimate. It tests consumer
phrasing such as short replies, misspellings, implicit needs, conjunctions,
metaphors, and natural category corrections. A valid fix must describe a
general language mechanism and must not mention a fixture ASIN at runtime.
