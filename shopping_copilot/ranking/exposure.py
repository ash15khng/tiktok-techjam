"""Session-aware recommendation novelty without changing candidate scores."""

from __future__ import annotations

from shopping_copilot.retrieval.models import CandidateEvidence


def unseen_first(
    candidates: list[CandidateEvidence],
    recommendation_exposure: set[str],
) -> list[CandidateEvidence]:
    """Keep score order within unseen and previously shown partitions."""

    if not recommendation_exposure:
        return candidates
    unseen = [item for item in candidates if item.parent_asin not in recommendation_exposure]
    shown = [item for item in candidates if item.parent_asin in recommendation_exposure]
    return [*unseen, *shown]
