from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass(frozen=True)
class ActionDecision:
    """Dialog action decision for the current turn."""
    ask_attribute: str | None
    message: str
    recommendations: tuple[str, ...]
    reason_codes: tuple[str, ...] = ()

