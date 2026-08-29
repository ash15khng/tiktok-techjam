"""Make one safe semantic-parser request without displaying credentials."""

from __future__ import annotations

import json

from shopping_copilot.config import MVPConfig
from shopping_copilot.contracts import SemanticParserError
from shopping_copilot.understanding.semantic_grounding import ground_semantic_interpretation
from shopping_copilot.understanding.semantic import configured_responses_parser_from_environment


def main() -> int:
    provider = configured_responses_parser_from_environment(MVPConfig())
    if provider is None:
        print("SoCLaaS parser is disabled or its URL, key, or model is missing.")
        return 2
    try:
        message = "I need comfortable, polished shoes for a humid outdoor wedding."
        context = "category=shoes"
        result = provider.interpret(message, context)
    except SemanticParserError as error:
        print(f"SoCLaaS request failed safely: {error}")
        return 1
    config = MVPConfig()
    grounded = ground_semantic_interpretation(
        result,
        raw_message=message,
        context=context,
        deterministic_updates=(),
        override=False,
        min_confidence=config.semantic_min_confidence,
        max_rewrite_terms=config.semantic_max_rewrite_terms,
    )
    print(
        json.dumps(
            {
                "model": provider.model,
                "query_rewrites": result.query_rewrites,
                "subjective_needs": result.subjective_needs,
                "slot_hypotheses": [
                    {
                        "attribute": item.attribute,
                        "value": item.value,
                        "confidence": item.confidence,
                        "evidence": item.evidence,
                    }
                    for item in result.slot_hypotheses
                ],
                "usage": {
                    "prompt_tokens": result.prompt_tokens,
                    "completion_tokens": result.completion_tokens,
                },
                "accepted_for_retrieval": {
                    "query_rewrites": grounded.query_rewrites,
                    "slot_updates": [
                        {
                            "attribute": item.attribute.value,
                            "value": item.value,
                            "source": item.source,
                        }
                        for item in grounded.slot_updates
                    ],
                },
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
