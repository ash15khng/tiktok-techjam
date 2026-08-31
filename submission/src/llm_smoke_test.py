"""Make one safe semantic-parser request without displaying credentials."""

from __future__ import annotations

import json

from submission.src.config import AgentConfig
from submission.src.contracts import SemanticParserError
from submission.src.understanding.semantic_grounding import ground_semantic_interpretation
from submission.src.understanding.semantic import configured_responses_parser_from_environment


def main() -> int:
    """Run one fixed paid probe and print only safe, structured diagnostics."""

    provider = configured_responses_parser_from_environment(AgentConfig())
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
    config = AgentConfig()
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
