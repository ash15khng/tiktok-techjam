from __future__ import annotations

import math
import statistics
from collections import Counter
from typing import Mapping, Sequence

from shopping_copilot.indexing.store import CatalogIndex
from shopping_copilot.retrieval.models import CandidateEvidence, RetrievalRequest


class RetrievalAssessor:
    """Computes target-blind query performance prediction (QPP) features across candidate pools."""

    def __init__(self, catalog_index: CatalogIndex) -> None:
        self.catalog_index = catalog_index

    def compute_generator_agreement(
        self,
        generator_results: Mapping[str, Sequence[tuple[str, float]]],
        top_n: int = 50,
    ) -> float:
        """Computes mean pairwise Jaccard similarity across top-N candidate pools."""
        pools = [
            set(asin for asin, _ in res[:top_n])
            for res in generator_results.values()
            if res
        ]
        if len(pools) < 2:
            return 1.0

        jaccards: list[float] = []
        for i in range(len(pools)):
            for j in range(i + 1, len(pools)):
                union = pools[i] | pools[j]
                inter = pools[i] & pools[j]
                if union:
                    jaccards.append(len(inter) / len(union))
                else:
                    jaccards.append(0.0)

        return statistics.mean(jaccards) if jaccards else 1.0

    def compute_category_entropy(self, candidate_asins: Sequence[str], top_n: int = 50) -> float:
        """Calculates normalized Shannon entropy of categories in top candidates."""
        cats: list[str] = []
        for asin in candidate_asins[:top_n]:
            rec = self.catalog_index.get_product(asin)
            if rec and rec.categories:
                cats.append(rec.categories[-1])  # most specific category

        if not cats:
            return 0.0

        counts = Counter(cats)
        total = len(cats)
        num_cats = len(counts)
        if num_cats <= 1:
            return 0.0

        entropy = -sum((cnt / total) * math.log(cnt / total) for cnt in counts.values())
        max_entropy = math.log(num_cats)
        return min(1.0, max(0.0, entropy / max_entropy))

    def compute_nqc(self, candidate_scores: Sequence[float], top_n: int = 20) -> float:
        """Calculates Normalized Query Commitment (score dispersion)."""
        scores = list(candidate_scores[:top_n])
        if len(scores) < 2:
            return 0.0
        mean_score = statistics.mean(scores)
        stdev = statistics.stdev(scores)
        nqc = stdev / (abs(mean_score) + 1e-9)
        return min(1.0, max(0.0, nqc / 2.0))
