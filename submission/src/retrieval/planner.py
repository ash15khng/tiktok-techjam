"""Soft focused/exploratory route blending."""

from __future__ import annotations

import math

from submission.src.config import AgentConfig
from submission.src.dialog.models import ActiveState
from submission.src.retrieval.models import RetrievalPlan


class RetrievalPlanner:
    """Convert current evidence into a soft blend of five retrieval routes."""

    def __init__(self, config: AgentConfig) -> None:
        self.config = config

    def plan(self, active: ActiveState) -> RetrievalPlan:
        """
        Return route weights for one snapshot of active state.
        This is how we influence results from buying/browsing behaviour.
        Those browsing would likely have less hard evidence and more exploratory queries, while those buying would have more hard evidence and more focused queries.
        """

        hard_evidence = len(active.preference_phrases) + len(active.exclusions)
        category_evidence = int(bool(active.category_phrases))
        z = (
            self.config.focus_intercept
            + self.config.focus_preference_weight * hard_evidence
            + self.config.focus_category_weight * category_evidence
        )
        focus_score = 1.0 / (1.0 + math.exp(-z)) # 0 is browsing, 1 is buying with strict constriants
        focused = dict(self.config.focused_route_weights)
        exploratory = dict(self.config.exploratory_route_weights)
        weights = {
            name: focus_score * focused[name] + (1.0 - focus_score) * exploratory[name]
            for name in focused
        }
        return RetrievalPlan(focus_score, weights, self.config.candidate_depth)
