from __future__ import annotations

from typing import Mapping

from shopping_copilot.retrieval.models import RetrievalPlan

# Endpoint weight configurations from architecture specifications
FOCUSED_WEIGHTS: dict[str, float] = {
    "title_fts": 1.0,
    "field_fts": 0.8,
    "attribute_posting": 1.3,
}

EXPLORATORY_WEIGHTS: dict[str, float] = {
    "title_fts": 0.7,
    "field_fts": 1.0,
    "attribute_posting": 0.9,
}

DEFAULT_LIMITS: dict[str, int] = {
    "title_fts": 100,
    "field_fts": 200,
    "attribute_posting": 150,
}


class RetrievalPlanner:
    """Plans generator weights and candidate pool depths based on continuous need assessment."""

    def plan(self, focus_score: float) -> RetrievalPlan:
        score = min(1.0, max(0.0, focus_score))
        weights: dict[str, float] = {}

        for gen_name in DEFAULT_LIMITS.keys():
            fw = FOCUSED_WEIGHTS.get(gen_name, 1.0)
            ew = EXPLORATORY_WEIGHTS.get(gen_name, 1.0)
            blended = score * fw + (1.0 - score) * ew
            weights[gen_name] = round(blended, 4)

        return RetrievalPlan(
            focus_score=score,
            generator_weights=weights,
            generator_limits=dict(DEFAULT_LIMITS),
            reason_codes=("focus_score_blended",),
        )
