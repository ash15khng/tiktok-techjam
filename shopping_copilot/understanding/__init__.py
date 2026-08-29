"""Message understanding and intent parsing subsystem."""

from __future__ import annotations

from shopping_copilot.understanding.models import (
    Attribute,
    IntentFrame,
    InterpretationAmbiguity,
    Relation,
    SlotUpdate,
)

__all__ = [
    "Attribute",
    "Relation",
    "SlotUpdate",
    "InterpretationAmbiguity",
    "IntentFrame",
]

