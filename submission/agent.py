"""Official TechJam Agent entry point.

Input contract:
    ``Agent(catalog_path)`` receives the frozen JSONL catalog path. ``reset``
    receives a session ID and anonymized profile. ``respond`` receives the same
    session ID, one customer message, a 1-based turn number, and ``top_k=10``.

Output contract:
    ``respond`` returns a customer-facing message, one allowed
    ``ask_attribute`` (or ``None``), up to ten ordered catalog ``parent_asin``
    recommendations, and non-negative token usage. Product logic is implemented
    in :class:`submission.src.agent.ShoppingAgent`.
"""

from __future__ import annotations

from pathlib import Path

from submission.src.agent import ShoppingAgent


class Agent:
    """Adapter exposing the exact organizer-facing ``reset/respond`` API."""

    def __init__(self, catalog_path: str | Path = "data/catalog.jsonl") -> None:
        self._agent = ShoppingAgent(catalog_path)

    def reset(self, session_id: str, user_profile: dict) -> None:
        """Start or replace one isolated session using an anonymized profile."""

        self._agent.reset(session_id, user_profile)

    def respond(self, session_id: str, user_message: str, turn: int, top_k: int) -> dict:
        """Return one contract-safe response for the current customer turn."""

        return self._agent.respond(session_id, user_message, turn, top_k)
