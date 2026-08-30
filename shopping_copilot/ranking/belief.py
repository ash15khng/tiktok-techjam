from __future__ import annotations

import math
from typing import Sequence


def compute_candidate_belief(scores: Sequence[float], temperature: float = 0.20) -> list[float]:
    """Computes softmax probability distribution over candidate scores."""
    if not scores:
        return []

    max_s = max(scores)
    exp_scores = [math.exp((s - max_s) / max(temperature, 1e-6)) for s in scores]
    total = sum(exp_scores)
    if total <= 1e-12:
        return [1.0 / len(scores)] * len(scores)

    return [e / total for e in exp_scores]


def compute_top10_confidence(
    top10_belief_mass: float,
    generator_agreement: float,
    top10_stability: float = 0.80,
    constraint_evidence_coverage: float = 1.0,
    top10_margin: float = 0.50,
    category_entropy: float = 0.20,
) -> float:
    """Calculates overall target-blind Top-10 confidence score."""
    raw = (
        0.25 * min(1.0, max(0.0, top10_belief_mass))
        + 0.20 * min(1.0, max(0.0, generator_agreement))
        + 0.20 * min(1.0, max(0.0, top10_stability))
        + 0.15 * min(1.0, max(0.0, constraint_evidence_coverage))
        + 0.10 * min(1.0, max(0.0, top10_margin))
        + 0.10 * (1.0 - min(1.0, max(0.0, category_entropy)))
    )
    return round(min(1.0, max(0.0, raw)), 4)

