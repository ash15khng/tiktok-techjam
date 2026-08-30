from __future__ import annotations

from pathlib import Path
from typing import Any

from shopping_copilot.agent import ShoppingAgent


class Agent:
    """Production shopping copilot agent powering the TechJam evaluation harness."""

    def __init__(self, catalog_path: str | Path = "data/catalog.jsonl") -> None:
        self._delegate = ShoppingAgent(catalog_path=catalog_path)

    def reset(self, session_id: str, user_profile: dict[str, Any]) -> None:
        """Initializes or resets conversation session."""
        self._delegate.reset(session_id, user_profile)

    def respond(
        self,
        session_id: str,
        user_message: str,
        turn: int,
        top_k: int = 10,
    ) -> dict[str, Any]:
        """Processes turn and returns message, ask_attribute, and recommendations."""
        return self._delegate.respond(
            session_id=session_id,
            user_message=user_message,
            turn=turn,
            top_k=top_k,
        )
