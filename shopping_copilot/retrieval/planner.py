"""Soft focused/exploratory route blending."""

from __future__ import annotations

import math

from shopping_copilot.config import MVPConfig
from shopping_copilot.dialog.models import ActiveState
from shopping_copilot.retrieval.models import RetrievalPlan


class RetrievalPlanner:
    def __init__(self, config: MVPConfig) -> None:
        self.config = config

    def plan(self, active: ActiveState) -> RetrievalPlan:
        hard_evidence = len(active.preference_phrases) + len(active.exclusions)
        category_evidence = int(bool(active.category_phrases))
        z = -1.1 + 0.95 * hard_evidence + 0.35 * category_evidence
        focus_score = 1.0 / (1.0 + math.exp(-z))
        focused = dict(self.config.focused_route_weights)
        exploratory = dict(self.config.exploratory_route_weights)
        weights = {
            name: focus_score * focused[name] + (1.0 - focus_score) * exploratory[name]
            for name in focused
        }
        return RetrievalPlan(focus_score, weights, self.config.candidate_depth)
