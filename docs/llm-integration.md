# Optional Semantic Parser

## Status

The OpenAI Responses API adapter is implemented but disabled by default. It has
mocked HTTP, schema, token-accounting, gating, and fallback tests. It has not been
called with a real API key, so no model quality, latency, cost, or score claim is
made.

## Enable it

Copy `.env.example` values into your local ignored environment configuration and
set all three variables:

```text
SHOPPING_COPILOT_LLM_ENABLED=1
SHOPPING_COPILOT_LLM_MODEL=<model available to the project>
OPENAI_API_KEY=<local secret>
```

The application does not load `.env` files itself. Export the values through the
shell, deployment environment, or the team's chosen secret manager. Never commit
the key.

## Expected behavior

The model is called only for subjective or complex messages such as:

> I need something polished but comfortable for a humid outdoor wedding.

It returns strict structured data:

- up to three short catalog-search rewrites;
- up to five subjective needs;
- up to eight soft attribute hypotheses with supporting evidence.

The deterministic parser remains authoritative for supported budgets,
high-confidence exclusions, corrections, and `ANY`. Model hypotheses cannot
create ASINs and their confidence is capped at 0.70 before any future catalog
grounding. Complex alternatives and implicit size language still need corpus
coverage before the model path can be considered reliable.

Simple replies and evaluator-shaped constraint messages skip the API. Timeouts,
HTTP errors, incomplete responses, invalid JSON, or invalid fields become an
empty semantic result; normal lexical retrieval continues.

## Before production use

1. Choose and disclose an available model explicitly.
2. Run a hand-authored paraphrase corpus and the official evaluator.
3. Record parse accuracy, score delta, p95 latency, tokens, cost, and fallback rate.
4. Keep the adapter only if measured gains justify those costs.
5. Confirm the judging environment permits network access; otherwise use the
   deterministic default or a tested local model.

Implementation follows the official [OpenAI Responses API reference](https://developers.openai.com/api/reference/cli/resources/responses/methods/create), including structured `text.format`, bounded output, `store: false`, and response token usage.
