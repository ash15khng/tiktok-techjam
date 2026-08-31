"""Evidence-grounded customer-facing list explanations."""

from __future__ import annotations

from submission.src.dialog.models import ActiveState


# More phrases/characters explain more evidence but make every response longer;
# fewer improve brevity but can hide why ranking changed. One category plus two
# preferences fit the tested conversations; this is presentation-only.
MAX_CATEGORY_EXPLANATIONS = 1
MAX_PREFERENCE_EXPLANATIONS = 2
MAX_EXPLANATION_VALUE_CHARS = 90


def explain(active: ActiveState) -> str:
    """Return a short explanation using only current customer-visible evidence."""

    evidence = [
        *active.category_phrases[-MAX_CATEGORY_EXPLANATIONS:],
        *active.preference_phrases[-MAX_PREFERENCE_EXPLANATIONS:],
    ]
    if not evidence:
        return "I ranked these using the available catalog evidence."
    readable = "; ".join(value[:MAX_EXPLANATION_VALUE_CHARS] for value in evidence)
    return f"I ranked these using your current request: {readable}."
