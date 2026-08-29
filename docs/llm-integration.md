# SoCLaaS Semantic Parser

## Status

The optional semantic parser uses the SoCLaaS Responses-compatible endpoint and
is disabled unless its enable flag, model, HTTPS base URL, and API key are all
present. The deterministic interpreter remains the fallback.

The adapter has mocked contract tests, a successful live compatibility probe,
and one paired 50-session public-set ablation. The ablation confirmed bounded
usage and safe fallback but measured no score improvement. It does not establish
model quality, p95 latency, monetary cost, or private-set value.

## Local `.env` setup

Copy `.env.example` to `.env`, then edit only the ignored `.env` file:

```text
SHOPPING_COPILOT_LLM_ENABLED=1
SHOPPING_COPILOT_LLM_MAX_CALLS=64
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
accepted from the file. The call cap is shared across the process; lower it for
demos or development when a stricter spending ceiling is needed.

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
$env:SHOPPING_COPILOT_LLM_MAX_CALLS = "64"
$env:SHOPPING_COPILOT_LLM_MODEL = "llama3.1:8b"
$env:SHOPPING_COPILOT_LLM_TIMEOUT_SECONDS = "6"
$env:SOCLAAS_BASE_URL = "https://your-real-gateway.example/v1"
$env:SOCLAAS_API_KEY = "paste-the-key-in-your-own-terminal"
python -m shopping_copilot.llm_smoke_test
```

Clear the session value afterwards:

```powershell
Remove-Item Env:SOCLAAS_API_KEY
```

An external secret file is also supported. Create it outside the repository,
restrict its permissions, then set its path before running Python:

```powershell
$env:SHOPPING_COPILOT_ENV_FILE = "C:\private\techjam-soclaas.env"
python -m shopping_copilot.llm_smoke_test
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
- `temperature=0`.

The adapter does not send `background`, `store`, `text.format`, hosted tools, or
`previous_response_id`. Temporary gateway response state is unnecessary because
the current Context Snapshot is supplied on every call. The returned JSON is
validated locally; a single `json` code fence is tolerated for the 8B model.
Successful repeated message/context pairs are cached, and cache hits report zero
tokens because no new request is made. Failed requests are not retried.

## Product behavior and fallback

The model is called only for subjective or complex messages such as:

> I need something polished but comfortable for a humid outdoor wedding.

It may return short query rewrites, subjective needs, and soft `feature`,
`style`, or `use_case` hypotheses. Rewrites must share an anchor with the current
message or Active State. Slot hypotheses require confidence of at least `0.55`
and an exact evidence span. Deterministic evidence wins on conflict.

Subjective summaries are retained for diagnostics but are not added directly to
BM25. Model-produced identifiers, negated rewrites, unsupported attributes, and
ungrounded hints are discarded. Numeric comparisons, exclusions, corrections,
catalog identity, and contextual short answers remain deterministic.

Timeouts, HTTP errors, incomplete responses, invalid JSON, or invalid fields
become an empty semantic result during normal agent operation. Run the one-call
smoke test first so configuration or response-format failures are visible:

```powershell
python -m shopping_copilot.llm_smoke_test
```

Only after that succeeds should the team run the official evaluator and record
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
category, material, and color without sufficient support; the retrieval
grounder rejected those slots. The prompt was then narrowed to request only the
three accepted soft attributes. No further live call and no paid public-set
evaluation were run.

A no-network replay of all 200 public sessions found 13 eligible semantic calls
and 12 unique message/context pairs. This estimates call volume only, not score.

A later paired run sampled 50 public sessions with seed `20260829`. Its dry gate
selected 2 of 103 parsed turns. Live mode was hard-capped at those 2 provider
attempts, with no retries: one succeeded, one failed safely, and the run reported
348 input plus 89 output tokens. LLM-off and LLM-on both scored Hit Rate@10
`1.000`, MRR `0.710802`, MTTC `2.06`, and TechnicalScore `0.892041`; every
session-level hit turn and rank was identical. The current public evidence does
not justify enabling billed semantics for score. Keep it off by default until a
curated ambiguity corpus demonstrates retrieval-relevant gains, then consider a
gate that also requires low deterministic retrieval confidence. Provider pricing
was not supplied, so monetary cost is not claimed.

The request shape follows the official [OpenAI Responses API reference](https://developers.openai.com/api/reference/cli/resources/responses/methods/create), while the supported-field subset and gateway-state limitations come from the SoCLaaS documentation supplied to the team.
