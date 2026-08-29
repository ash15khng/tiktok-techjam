# Shopping Copilot

> Ask less. Understand more. Surface the exact product sooner.

Online search works well when customers already know the catalog's language.
Real customers often do not. They say things like "my ears get itchy," "something
for a wet commute," or simply answer a follow-up with "blue/". Shopping Copilot
turns that evolving conversation into a ranked Top 10 without making the customer
repeat themselves or complete a long questionnaire.

This repository is our entry for the **TechJam 2026 Conversational E-Commerce
Search Challenge**. The objective is exacting: find one hidden product from a
frozen 50,000-product catalog, rank it as highly as possible, and do so within ten
turns.

## Results at a glance

Results below use the unmodified 200-session public evaluator with the optional
LLM disabled.

| Metric | Published starter | Shopping Copilot |
|---|---:|---:|
| Hit Rate@10 | 0.125 | **0.995** |
| MRR | 0.068034 | **0.635746** |
| MTTC | 9.81 turns | **2.245 turns** |
| Efficiency | — | **0.8755** |
| TechnicalScore | 0.107 | **0.863324** |

These are public-development results, not a claim about the private 800-session
evaluation. One public target remains unfound.

## The product experience

Shopping Copilot behaves like a focused shop assistant:

- it recommends products on every usable turn instead of withholding results;
- it asks one question only when the answer could materially improve the ranking;
- it understands short contextual replies such as `Nike`, `7`, `80`, `blue/`, or
  `no preference`;
- it removes stale preferences when the customer changes their mind;
- it treats the anonymized profile as a soft hint, never as permission to override
  the current request; and
- it always returns valid, unique `parent_asin` values from the frozen catalog.

For example:

```text
Customer: I need running shoes under $100, preferably blue, no leather.

Agent state:
  category     = running shoes
  budget_max   = 100
  color        = blue
  exclude      = leather

Agent response:
  Top 10 available now + one useful follow-up question
```

If the customer later says, "Actually, make it waterproof instead," the agent
removes the superseded preference before it searches again. Products rejected
under the old intent are also eligible again under the new intent.

## Why this is different

### Conversation is state, not a longer query

Messages are reduced into typed, inspectable state: category, hard constraints,
soft preferences, exclusions, budget, no-preference markers, and provenance.
Corrections replace stale evidence rather than appending contradictory text to a
prompt.

### Asking and recommending happen together

Every turn is a chance to hit the target. The agent returns its current Top 10
while asking the most valuable unresolved question. Candidate coverage and
diversity estimate whether a question is worth spending a turn on.

### Retrieval uncertainty controls expensive intelligence

The reliable path is deterministic and offline. An optional LLM is considered
only after initial retrieval exposes a genuine language or coverage problem. It
may translate consumer language into anchored catalog-search phrases, but it
cannot invent product IDs, choose the final ranking, or override explicit facts.

### Several weak signals become one robust ranking

Five inexpensive candidate routes look at different evidence: full fields,
titles, focused constraints, category relevance, and category-conditioned
popularity. Weighted Reciprocal Rank Fusion combines their candidates, then a
lightweight reranker scores the complete bounded union using coverage, phrase
matches, constraints, popularity, profile overlap, and exclusions.

## System flow

```text
Customer message + anonymized profile + current session state
                              |
                              v
              Deterministic message interpreter
                              |
                              v
              Typed Active State with provenance
                              |
                              v
       Five lexical candidate generators (SQLite FTS5)
                              |
                              v
          Weighted RRF -> full-union lightweight reranker
                              |
                 +------------+------------+
                 |                         |
                 v                         v
       Retrieval confidence        Optional semantic rewrite
       + question value             (strict, grounded, capped)
                 |                         |
                 +------------+------------+
                              |
                              v
             Ask when useful + return a guarded Top 10
```

The optional semantic branch performs at most one grounded state update and one
reretrieval. Failure, timeout, invalid output, or a disabled network leaves the
offline result intact.

## Evidence by scenario

| Scenario | Sessions | Hit Rate@10 | MRR | MTTC |
|---|---:|---:|---:|---:|
| Buying | 80 | 0.9875 | 0.623095 | 1.775 |
| Browsing | 80 | 1.0000 | 0.601935 | 2.0125 |
| Intent Override | 30 | 1.0000 | 0.737394 | 3.866667 |
| Boundary | 10 | 1.0000 | 0.7025 | 3.000 |

A separate 14-case natural-language stress suite uses catalog targets outside
the public 200. The deterministic system reaches 0.857143 Hit Rate. An offline
ideal-rewrite oracle reaches 1.000, demonstrating that catalog-grounded semantic
expansion can close real language gaps. The live model has not yet improved a
measured result, so paid semantics remains disabled by default.

## Performance and safety

Local measurements over a 40-request broad-query audit:

- 2.45 s catalog startup;
- 230 ms mean response time;
- 265 ms p95 response time;
- 274 MiB steady working set after load and one response; and
- zero model tokens and $0 marginal API cost on the canonical public run.

The runtime never reads labels, evaluator internals, hidden intent cards, raw
reviews, or user identities. Missing catalog metadata remains unknown rather
than being treated as a contradiction. The response guard removes invalid and
duplicate IDs and caps scored output at ten.

## Run it

Requirements:

- Python 3.10 or later;
- a verified `data/catalog.jsonl`; and
- no external service for the default path.

PowerShell:

```powershell
$env:SHOPPING_COPILOT_LLM_ENABLED = "0"
python -m unittest discover -v
python -m evaluator.local_evaluator
```

macOS or Linux:

```bash
SHOPPING_COPILOT_LLM_ENABLED=0 python -m unittest discover -v
SHOPPING_COPILOT_LLM_ENABLED=0 python -m evaluator.local_evaluator
```

The evaluator writes `results.json`. Do not edit the evaluator or public labels
when reporting results.

## Where to start reading

| What you want to understand | File |
|---|---|
| Required entry point | [`starter/agent.py`](starter/agent.py) |
| End-to-end decision loop | [`shopping_copilot/agent.py`](shopping_copilot/agent.py) |
| Typed state and contracts | [`shopping_copilot/contracts.py`](shopping_copilot/contracts.py) |
| Intent and constraint extraction | [`shopping_copilot/understanding/`](shopping_copilot/understanding/) |
| Candidate generation and ranking | [`shopping_copilot/retrieval/`](shopping_copilot/retrieval/) |
| Clarification policy | [`shopping_copilot/dialog/`](shopping_copilot/dialog/) |
| Full technical architecture | [`docs/architecture.md`](docs/architecture.md) |
| End-to-end and component flowcharts | [`docs/system-flowcharts.md`](docs/system-flowcharts.md) |
| Experiments, including failures | [`docs/findings.md`](docs/findings.md) |
| LLM boundaries and measured behavior | [`docs/llm-integration.md`](docs/llm-integration.md) |

## What we learned from past TechJam winners

This README's structure is informed by publicly visible, winner-badged TechJam
projects. These are presentation and engineering lessons, not evidence that the
same judging outcome will repeat in 2026:

- **Lead with a recognizable user pain.** [EzSeek](https://devpost.com/software/ezseek)
  begins with the shortcomings of conventional shopping and connects each
  feature to a customer outcome. We keep that clarity while narrowing our scope
  to the competition's exact conversational-search objective.
- **Make the technical thesis easy to inspect.** [Denoising Reviews With
  Mamba](https://devpost.com/software/denoising-reviews-with-mamba) explains a
  staged architecture and why each stage exists. Our thesis is similarly
  explicit: typed conversation state, diverse retrieval, evidence fusion, then
  bounded reranking.
- **Show measurements and operational constraints.** [PrivaStream](https://devpost.com/software/live-privacy-shield)
  reports model quality, latency, scalability, and fail-safe behavior. We report
  public metrics, scenario results, latency, memory, tokens, and known limits.
- **Right-size AI for the actual interaction.** [Honey Badger Sales
  Helper](https://devpost.com/software/honeybadgers) chose a small local model for
  responsiveness and privacy. Our LLM is optional and gated; the dependable path
  remains offline and inexpensive.
- **Use personalization with an understandable mechanism.** [Adopting GenAI for
  personalized endorsements](https://devpost.com/software/adopting-genai-for-personalized-endorsements)
  makes user context central to discovery. We use only the permitted anonymized
  profile, cap its ranking influence, and let current-session evidence win.

The [2024](https://tiktoktechjam2024.devpost.com/project-gallery?page=1) and
[2025](https://tiktoktechjam2025.devpost.com/project-gallery) galleries are not
exhaustive records of every past project. The 2025 judging rules also emphasized
working execution, technical quality, innovation, problem fit, and impact; the
2026 challenge specification remains authoritative for this submission.

## Current limitations

- Public tuning may not transfer perfectly to the private set.
- The remaining public miss is a low-volume item in a large lexical tie group.
- Complex negation and first-class OR constraints need more corpus coverage.
- The strict function-tool LLM path is mocked but not yet live-validated.
- Live semantic tests consumed tokens without improving a measured score.
- Latency and memory must be repeated on the final judging machine.

## Built with

Python 3.10+, SQLite FTS5, JSONL, dataclasses, protocols, regular expressions,
weighted Reciprocal Rank Fusion, lightweight feature reranking, and `unittest`.
The optional semantic adapter targets a SoCLaaS Responses-compatible API and is
isolated behind a deterministic fallback.

## Data and attribution

The frozen catalog and sessions are derived from Amazon Reviews 2023 by McAuley
Lab, UCSD. See [`DATA_ATTRIBUTION.md`](DATA_ATTRIBUTION.md) before using or
redistributing the data.
