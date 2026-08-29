# SoCLaaS Semantic Parser

## Status

The optional semantic parser uses the SoCLaaS Responses-compatible endpoint and
is disabled unless its enable flag, model, HTTPS base URL, and API key are all
present. The deterministic interpreter remains the fallback.

The adapter has mocked contract tests but has not yet been measured with the
team's real gateway key. Do not claim model quality, latency, cost, or score
improvement until the live probe and controlled evaluator runs are recorded.

## Local `.env` setup

Copy `.env.example` to `.env`, then edit only the ignored `.env` file:

```text
SHOPPING_COPILOT_LLM_ENABLED=1
SHOPPING_COPILOT_LLM_MODEL=llama3.1:8b
SOCLAAS_BASE_URL=https://your-real-gateway.example/v1
SOCLAAS_API_KEY=replace-locally
```

Set `SOCLAAS_BASE_URL` to the URL immediately before `/responses`. A full URL
already ending in `/responses` is also accepted. Remote plain HTTP endpoints are
rejected; HTTP is allowed only for localhost development.

The application loads the repository `.env` without another package. Existing
OS environment variables take precedence, so deployment or terminal secrets
cannot be silently replaced by file values. Only the four documented runtime
keys are accepted from the file.

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
$env:SHOPPING_COPILOT_LLM_MODEL = "llama3.1:8b"
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

## Product behavior and fallback

The model is called only for subjective or complex messages such as:

> I need something polished but comfortable for a humid outdoor wedding.

It may return short query rewrites, subjective needs, and soft attribute
hypotheses with supporting evidence. It cannot create product IDs. Numeric
comparisons, negation, overrides, exact catalog grounding, and contextual short
answers remain authoritative in deterministic code.

Timeouts, HTTP errors, incomplete responses, invalid JSON, or invalid fields
become an empty semantic result during normal agent operation. Run the one-call
smoke test first so configuration or response-format failures are visible:

```powershell
python -m shopping_copilot.llm_smoke_test
```

Only after that succeeds should the team run the official evaluator and record
model name, latency, token use, cost, fallback rate, scenario metrics, and the
deterministic comparison.

The request shape follows the official [OpenAI Responses API reference](https://developers.openai.com/api/reference/cli/resources/responses/methods/create), while the supported-field subset and gateway-state limitations come from the SoCLaaS documentation supplied to the team.
