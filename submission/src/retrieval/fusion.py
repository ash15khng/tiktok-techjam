"""Rank-level fusion for heterogeneous candidate generators."""

from __future__ import annotations

from submission.src.retrieval.models import CandidateEvidence


def reciprocal_rank_fusion(
    generator_results: dict[str, list],
    weights: dict[str, float],
    *,
    k: int,
) -> list[CandidateEvidence]:
    evidence_by_id: dict[str, CandidateEvidence] = {}
    for generator, results in generator_results.items():
        weight = max(0.0, float(weights.get(generator, 0.0)))
        for rank, result in enumerate(results, 1):
            evidence = evidence_by_id.setdefault(result.parent_asin, CandidateEvidence(result.parent_asin))
            evidence.generator_ranks[generator] = rank
            evidence.raw_scores[generator] = result.raw_score
            evidence.rrf_score += weight / (k + rank)
    return sorted(
        evidence_by_id.values(),
        key=lambda item: (-item.rrf_score, item.parent_asin),
    )


def assess_results(generator_results: dict[str, list], fused: list[CandidateEvidence]):
    from submission.src.retrieval.models import RetrievalAssessment

    nonempty = [results for results in generator_results.values() if results]
    if len(nonempty) < 2:
        agreement = 0.0
    else:
        overlaps: list[float] = []
        for index, left in enumerate(nonempty):
            left_ids = {item.parent_asin for item in left[:20]}
            for right in nonempty[index + 1:]:
                right_ids = {item.parent_asin for item in right[:20]}
                union = left_ids | right_ids
                overlaps.append(len(left_ids & right_ids) / len(union) if union else 0.0)
        agreement = sum(overlaps) / len(overlaps) if overlaps else 0.0
    top10_stability = min(1.0, agreement * 2.5)
    return RetrievalAssessment(len(fused), agreement, top10_stability)
