# SoCLaaS Semantic Parser

## Status

The optional semantic parser uses the SoCLaaS Responses-compatible endpoint and
is disabled unless its enable flag, model, HTTPS base URL, and API key are all
present. The deterministic interpreter remains the fallback.

The adapter has mocked contract tests, a successful live compatibility probe,
a paired 50-session public-set ablation, and a separate 14-case natural-language
stress suite. Paid tests confirm bounded usage and safe fallback but have not yet
produced a score improvement. They do not establish model quality, p95 latency,
monetary cost, or private-set value.

## Local `.env` setup

Copy `.env.example` to `.env`, then edit only the ignored `.env` file:

```text
SHOPPING_COPILOT_LLM_ENABLED=1
SHOPPING_COPILOT_LLM_MAX_CALLS=16
SHOPPING_COPILOT_LLM_MODEL=llama3.1:8b
SHOPPING_COPILOT_LLM_TIMEOUT_SECONDS=6
SOCLAAS_BASE_URL=https://your-real-gateway.example/v1
SOCLAAS_API_KEY=replace-locally
```

Set `SOCLAAS_BASE_URL` to the URL immediately before `/responses`. A full URL
already ending in `/responses` is also accepted. Remote plain HTTP endpoints are
rejected; HTTP is allowed only for localhost development.

The application loads the repository `.env` without another package. Existing
OS environment variables take precedence, so deployment or terminal secrets
cannot be silently replaced by file values. Only documented runtime keys are
accepted from the file. The environment call cap is shared across the process;
runtime state also permits at most two semantic attempts per session. Lower the
process cap for demos or development when a stricter spending ceiling is needed.

`.env` is covered by `.gitignore`; `.env.example` contains placeholders only.
Verify before every commit:

```powershell
git check-ignore -v .env
git diff --cached -- .env .env.example
```

## Keeping the key outside the workspace

There is no line that can be added to `.env` or `.gitignore` that lets the
program read the key while guaranteeing that Codex cannot read the same file.
Git ignore prevents commits; it is not a filesystem permission boundary.

For a key that should not be stored in the workspace, omit `.env` and inject it
in the terminal that runs the agent:

```powershell
$env:SHOPPING_COPILOT_LLM_ENABLED = "1"
$env:SHOPPING_COPILOT_LLM_MAX_CALLS = "16"
$env:SHOPPING_COPILOT_LLM_MODEL = "llama3.1:8b"
$env:SHOPPING_COPILOT_LLM_TIMEOUT_SECONDS = "6"
$env:SOCLAAS_BASE_URL = "https://your-real-gateway.example/v1"
$env:SOCLAAS_API_KEY = "paste-the-key-in-your-own-terminal"
python -m submission.src.llm_smoke_test
```

Clear the session value afterwards:

```powershell
Remove-Item Env:SOCLAAS_API_KEY
```

An external secret file is also supported. Create it outside the repository,
restrict its permissions, then set its path before running Python:

```powershell
$env:SHOPPING_COPILOT_ENV_FILE = "C:\private\techjam-soclaas.env"
python -m submission.src.llm_smoke_test
```

This reduces accidental Git and workspace exposure, but any process running
with the same user privileges may still be able to access the credential. Use a
short-lived, least-privilege key and rotate it if it is ever printed or pasted
into chat.

## Request behavior

Every call is stateless and sends only SoCLaaS-supported fields:

- `model`;
- a string `input` containing the current message and compact Active State;
- `instructions` requiring one JSON object;
- `stream=false`;
- bounded `max_output_tokens`;
- `temperature=0`;
- one strict client-executed `function` tool;
- forced `tool_choice` for that function.

The adapter does not send `background`, `store`, `text.format`, hosted tools, or
`previous_response_id`. Temporary gateway response state is unnecessary because
the current Context Snapshot is supplied on every call. Function-call arguments
are validated locally; message-text JSON and a single `json` code fence remain a
compatibility fallback. Successful repeated message/context pairs are cached,
and cache hits report zero tokens because no new request is made. Failed requests
are not retried.

## Product behavior and fallback

The model has two mutually exclusive opportunities per turn. Before state
mutation, a preflight gate handles compound corrections/clearings, missing
category evidence, and difficult fallback spans. If preflight skips, the existing
retrieval-aware gate can call only for ambiguous or difficult language with weak
candidate stability. At most one request is made per turn. Short contextual
answers remain deterministic, and exact top-product evidence suppresses the
post-retrieval call.

An eligible example is:

> I need something polished but comfortable for a humid outdoor wedding.

The forced function schema permits `category`, `material`, `color`, `size`,
`style`, `brand`, `budget`, `feature`, and `use_case`. Every proposed slot carries
one explicit operation: `add`, `replace`, `exclude`, or `set_any`. The input is a
JSON-structured Active State plus the current message, so unrelated constraints
must persist across corrections. Rewrites must be concrete standalone catalog
queries containing only active positive evidence. Slot hypotheses require
confidence of at least `0.55` and an exact current-message evidence span;
hard-field values must also occur in that evidence. Deterministic explicit
evidence wins on conflict.

Subjective summaries are retained for diagnostics but are not added directly to
BM25. Model-produced identifiers, vague/negated rewrites, unsupported operations,
and ungrounded hints are discarded. Accepted rewrites live in a separate bounded
search-evidence field, not durable customer preferences, and are cleared by
corrections that could make them stale.

Timeouts, HTTP errors, incomplete responses, invalid JSON, or invalid fields
become an empty semantic result during normal agent operation. Run the one-call
smoke test first so configuration or response-format failures are visible:

```powershell
python -m submission.src.llm_smoke_test
```

Only after that succeeds should the team run a capped evaluation and record
model name, latency, token use, cost, fallback rate, scenario metrics, and the
deterministic comparison.

## Measured live probe

On 2026-08-29, three deliberate requests were attempted:

- the first completed but the initial strict parser rejected a list-shape
  deviation;
- the second reached the original 4-second timeout;
- the third succeeded with the provisional 6-second timeout in about 4.2
  seconds, reporting 343 input and 158 output tokens.

The successful response produced two anchored rewrites. It also inferred
category, material, and color without sufficient support, which local grounding
rejected. The current schema exposes all competition fields but requires hard
values to occur in an exact current-message evidence span.

A historical no-network replay of all 200 public sessions found 13 eligible
semantic calls and 12 unique message/context pairs. This estimates the former
lexical gate's call volume only, not score; the current structural gate requires
a new dry-run volume audit before paid use.

A later paired run sampled 50 public sessions with seed `20260829`. Its dry gate
selected 2 of 103 parsed turns. Live mode was hard-capped at those 2 provider
attempts, with no retries: one succeeded, one failed safely, and the run reported
348 input plus 89 output tokens. LLM-off and LLM-on both scored Hit Rate@10
`1.000`, MRR `0.710802`, MTTC `2.06`, and TechnicalScore `0.892041`; every
session-level hit turn and rank was identical. The current public evidence does
not justify enabling billed semantics for score. Keep it off by default until a
curated ambiguity corpus demonstrates retrieval-relevant gains, then consider a
gate threshold adjustment only through the working folds. The current gate
already requires low deterministic retrieval stability. Provider pricing
was not supplied, so monetary cost is not claimed.

On 2026-08-30, one deliberately capped smoke command was attempted after the
all-field operation schema was added. Local configuration reported the provider
disabled or incomplete, so no HTTP request, tokens, or cost occurred.

## Semantic matching boundary

The LLM improves semantic matching through query expansion: language such as
“walking on pillows” can become catalog terms such as “cushioned” or “memory
foam.” Those terms enter the five FTS generators, the structural generator when
its category/evidence gate resolves, and the bounded reranker’s IDF-coverage
score. This is semantic assistance, but not a neural
query-product cross-encoder.

A cross-encoder or listwise LLM reranker is not in the default runtime.
Cross-encoders jointly score each query-document pair after retrieval; adding one
here would introduce model memory, installation footprint, and per-candidate
latency. It remains adoption-gated until a target-disjoint test shows high
candidate recall but weak MRR.

## Hard-language evaluation

Version 2 of `tests/stress/hard_cases.json` contains 14 manually written cases
whose products are outside the 200 public targets. Deterministic results are Hit
Rate `0.857143`, MRR `0.7375`, and MTTC `1.357143`. An offline ideal-rewrite
provider recovers both misses at rank 5, producing Hit Rate `1.000`, MRR
`0.766071`, and MTTC `1.071429`. This demonstrates that safe query rewriting can
help the existing retriever without changing its deterministic behavior.

The two-factor escalation policy selected 4 of 15 hard-suite turns and zero
turns in the earlier seeded 50-session public sample. Two live text-output runs
were then capped at four attempts each with no retries:

| Run | Attempts | Completed | Failed | Reported tokens | Accepted hints | Score delta |
|---|---:|---:|---:|---:|---:|---:|
| Original safety prompt | 4 | 2 | 2 | 1,258 | 0 | 0 |
| Explicit rewrite examples | 4 | 3 | 1 | 2,127 | 0 | 0 |

Completed responses still produced no locally usable hints. The likely causes
are output-shape drift and an 8B model choosing empty arrays despite the prose
request. The adapter now forces a client-executed function tool with a strict
operation schema while permitting zero rewrites when none is safe. Mocked tests
pass. The latest capped smoke command found provider configuration
disabled/incomplete and made no request, so this exact schema still needs one
explicitly budgeted live compatibility call before any paid suite.

The request shape follows the official [OpenAI Responses API reference](https://developers.openai.com/api/reference/cli/resources/responses/methods/create), while the supported-field subset and gateway-state limitations come from the SoCLaaS documentation supplied to the team.

## Design references

- [ProductAgent (EMNLP Industry 2025)](https://aclanthology.org/2025.emnlp-industry.25/) supports structured conversational memory, candidate-aware clarification, and a closed retrieval loop.
- [CONQRR](https://arxiv.org/abs/2112.08558) motivates rewriting context-dependent turns into standalone retrieval queries.
- [Sentence Transformers: Retrieve and Re-Rank](https://www.sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html) explains why semantic cross-encoders belong on a bounded shortlist rather than the complete catalog.
