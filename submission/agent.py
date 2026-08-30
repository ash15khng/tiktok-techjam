"""
Official TechJam Agent entry point.

Inputs:
    As per competition defined in submission_rules.md:
    - Agent(catalog_path: str | Path = "data/catalog.jsonl") -> None:
    - reset(self, session_id: str, user_profile: dict) -> None:
    - respond(self, session_id: str, user_message: str, turn: int, top_k: int) -> dict:

Outputs:
    respond():
        dict {
            "message": user facing message,
            "ask_attribute": AnyOf["category", "material", "color", "size", "style", "brand", "budget", "feature", "use_case", "other"],
            "recommendations": [{"parent_asin": "B000..."}] [up to 10],
            "usage": {"prompt_tokens": int, "completion_tokens": int} (nullable if no usage)
        }

Product logic is implemented in :class:`src.agent.ShoppingAgent`.
"""

from __future__ import annotations

from pathlib import Path

from submission.src.agent import ShoppingAgent


class Agent:
    # Adapter to match competition API specification.
    # src/Agent.py implements the actual agent logic.

    def __init__(self, catalog_path: str | Path = "data/catalog.jsonl") -> None:
        self._agent = ShoppingAgent(catalog_path)

    def reset(self, session_id: str, user_profile: dict) -> None:
        # new session for given profile
        self._agent.reset(session_id, user_profile)

    def respond(self, session_id: str, user_message: str, turn: int, top_k: int) -> dict:
        # respond to user message with recommendations
        return self._agent.respond(session_id, user_message, turn, top_k)
