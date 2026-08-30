from __future__ import annotations

from typing import Mapping, Sequence

from shopping_copilot.retrieval.models import CandidateEvidence


class WeightedRRFFusion:
    """Merges ranked candidate lists from multiple generators using Weighted Reciprocal Rank Fusion."""

    def __init__(self, k: int = 60) -> None:
        self.k = k

    def fuse(
        self,
        generator_results: Mapping[str, Sequence[tuple[str, float]]],
        generator_weights: Mapping[str, float],
    ) -> dict[str, CandidateEvidence]:
        """Fuses candidate pools and populates CandidateEvidence records."""
        evidence_map: dict[str, CandidateEvidence] = {}

        for gen_name, candidates in generator_results.items():
            w = generator_weights.get(gen_name, 1.0)
            for rank_0, (asin, raw_score) in enumerate(candidates):
                rank_1 = rank_0 + 1
                if asin not in evidence_map:
                    evidence_map[asin] = CandidateEvidence(parent_asin=asin)

                ev = evidence_map[asin]
                ev.generator_ranks[gen_name] = rank_1
                ev.raw_scores[gen_name] = raw_score
                ev.rrf_score += w / (self.k + rank_1)

        # Min-max normalize RRF scores
        if evidence_map:
            max_rrf = max(ev.rrf_score for ev in evidence_map.values())
            min_rrf = min(ev.rrf_score for ev in evidence_map.values())
            span = max_rrf - min_rrf
            for ev in evidence_map.values():
                if span > 1e-9:
                    ev.rrf_score = (ev.rrf_score - min_rrf) / span
                else:
                    ev.rrf_score = 1.0

        return evidence_map
