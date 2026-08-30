"""Evidence-grounded customer-facing list explanations."""

from __future__ import annotations

from submission.src.dialog.models import ActiveState


def explain(active: ActiveState) -> str:
    """Return a short explanation using only current customer-visible evidence."""

    evidence = [*active.category_phrases[-1:], *active.preference_phrases[-2:]]
    if not evidence:
        return "I ranked these using the available catalog evidence."
    readable = "; ".join(value[:90] for value in evidence)
    return f"I ranked these using your current request: {readable}."
