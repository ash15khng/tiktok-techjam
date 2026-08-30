"""Fuse generator outputs and summarize their target-blind agreement.

Input is a mapping from generator name to ordered catalog search results. Output
is one deduplicated candidate list plus an optional retrieval assessment used by
the dialog and semantic-call policies.
"""

from __future__ import annotations

from submission.src.catalog.models import CatalogSearchResult
from submission.src.retrieval.models import CandidateEvidence, RetrievalAssessment


def reciprocal_rank_fusion(
    generator_results: dict[str, list[CatalogSearchResult]],
    weights: dict[str, float],
    *,
    k: int,
) -> list[CandidateEvidence]:
    """Merge candidate lists from multiple generators using Weighted Reciprocal Rank Fusion."""

    evidence_by_id: dict[str, CandidateEvidence] = {}
    for generator, results in generator_results.items():
        weight = max(0.0, float(weights.get(generator, 0.0)))
        for rank, result in enumerate(results, 1):
            evidence = evidence_by_id.setdefault(
                result.parent_asin,
                CandidateEvidence(result.parent_asin),
            )
            evidence.generator_ranks[generator] = rank
            evidence.raw_scores[generator] = result.raw_score
            evidence.rrf_score += weight / (k + rank)
    return sorted(
        evidence_by_id.values(),
        key=lambda item: (-item.rrf_score, item.parent_asin),
    )


def assess_results(
    generator_results: dict[str, list[CatalogSearchResult]],
    fused: list[CandidateEvidence],
    *,
    overlap_depth: int,
    stability_scale: float,
) -> RetrievalAssessment:
    """
    Summarize candidate count and pairwise top-list overlap.

    ``top10_stability`` measure of how much top results from routes overlap
    ``overlap_depth`` and ``stability_scale`` come from :class:`AgentConfig`.
    """

    overlap_depth = max(1, int(overlap_depth))
    stability_scale = max(0.0, float(stability_scale))
    nonempty = [results for results in generator_results.values() if results]
    if len(nonempty) < 2:
        agreement = 0.0
    else:
        overlaps: list[float] = []
        for index, left in enumerate(nonempty):
            left_ids = {item.parent_asin for item in left[:overlap_depth]}
            for right in nonempty[index + 1:]:
                right_ids = {item.parent_asin for item in right[:overlap_depth]}
                union = left_ids | right_ids
                overlaps.append(len(left_ids & right_ids) / len(union) if union else 0.0)
        agreement = sum(overlaps) / len(overlaps) if overlaps else 0.0
    top10_stability = min(1.0, agreement * stability_scale)
    return RetrievalAssessment(len(fused), agreement, top10_stability)
