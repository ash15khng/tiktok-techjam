"""Membership-preserving ordering signals for the final recommendation list.

Input is a relevance-ranked candidate union. Only the first configured Top-K
members may be reordered; no weak prior in this module can add or remove an ID
from that membership. Output is the same candidate objects in a new order.
"""

from __future__ import annotations

import math

from submission.src.catalog.normalization import tokenize
from submission.src.catalog.store import CatalogStore
from submission.src.config import AgentConfig
from submission.src.dialog.models import ActiveState
from submission.src.retrieval.models import CandidateEvidence


class FrozenTopKOrderer:
    """Reorder frozen Top-K membership using bounded secondary evidence."""

    def __init__(self, store: CatalogStore, config: AgentConfig) -> None:
        self.store = store
        self.config = config

    def order(
        self,
        candidates: list[CandidateEvidence],
        active: ActiveState,
        customer_profile: dict,
        *,
        allow_popularity: bool = True,
    ) -> list[CandidateEvidence]:
        """Return a reordered Top-K followed by the untouched remainder.

        ``candidates`` must already be ordered by relevance and session exposure.
        The base reciprocal-rank term preserves that order unless bounded phrase,
        popularity, or profile evidence is strong enough to break it.
        """

        if not self.config.membership_preserving_ordering or len(candidates) < 2:
            return candidates
        membership_size = min(self.config.max_recommendations, len(candidates))
        frozen = candidates[:membership_size]
        remainder = candidates[membership_size:]
        phrase_evidence = self._phrase_evidence(candidates, frozen, active)
        maximum_phrase_evidence = max(phrase_evidence.values(), default=0.0)
        profile_terms = (
            self._profile_terms(customer_profile)
            if self.config.ordering_profile_weight > 0.0
            else frozenset()
        )
        denominator = float(self.config.rrf_k + 1)

        ordered: list[tuple[float, int, CandidateEvidence]] = []
        for base_rank, candidate in enumerate(frozen, start=1):
            phrase_raw = phrase_evidence.get(candidate.parent_asin, 0.0)
            phrase_normalized = (
                phrase_raw / maximum_phrase_evidence
                if maximum_phrase_evidence > 0.0
                else 0.0
            )
            product = self.store.get(candidate.parent_asin)
            popularity = self._popularity(product.rating_number)
            product_terms = self.store.product_terms(candidate.parent_asin)
            profile_overlap = (
                len(product_terms & profile_terms) / len(profile_terms)
                if profile_terms
                else 0.0
            )
            base_score = 1.0 / (self.config.rrf_k + base_rank)
            phrase_bonus = (
                self.config.phrase_rarity_order_weight
                * phrase_normalized
                / denominator
            )
            popularity_bonus = (
                self.config.ordering_popularity_weight
                * popularity
                / denominator
                if allow_popularity
                else 0.0
            )
            profile_bonus = (
                self.config.ordering_profile_weight
                * min(1.0, profile_overlap)
                / denominator
            )
            ordering_score = (
                base_score + phrase_bonus + popularity_bonus + profile_bonus
            )
            candidate.raw_scores.update(
                {
                    "ordering_base_rank": base_score,
                    "ordering_phrase_rarity": phrase_raw,
                    "ordering_phrase_bonus": phrase_bonus,
                    "ordering_popularity_bonus": popularity_bonus,
                    "ordering_profile_bonus": profile_bonus,
                    "ordering_score": ordering_score,
                }
            )
            ordered.append((ordering_score, base_rank, candidate))

        ordered.sort(
            key=lambda item: (-item[0], item[1], item[2].parent_asin)
        )
        return [*(item[2] for item in ordered), *remainder]

    def _phrase_evidence(
        self,
        candidates: list[CandidateEvidence],
        frozen: list[CandidateEvidence],
        active: ActiveState,
    ) -> dict[str, float]:
        """Return inverse pool-frequency evidence for exact disclosed phrases."""

        if self.config.phrase_rarity_order_weight <= 0.0:
            return {}
        phrases = tuple(
            dict.fromkeys(
                phrase
                for value in active.preference_phrases
                if (
                    phrase := " ".join(
                        tokenize(value, drop_stopwords=False)[
                            : self.config.phrase_rarity_max_terms
                        ]
                    )
                )
            )
        )
        if not phrases:
            return {}
        pool = candidates[: self.config.phrase_rarity_pool_depth]
        pool_text = {
            candidate.parent_asin: self.store.product_token_text(candidate.parent_asin)
            for candidate in pool
        }
        frequencies = {
            phrase: sum(phrase in text for text in pool_text.values())
            for phrase in phrases
        }
        selective = {
            phrase: frequency
            for phrase, frequency in frequencies.items()
            if 0 < frequency < len(pool_text)
        }
        return {
            candidate.parent_asin: sum(
                1.0 / frequency
                for phrase, frequency in selective.items()
                if phrase in pool_text.get(candidate.parent_asin, "")
            )
            for candidate in frozen
        }

    def _popularity(self, rating_count: int) -> float:
        """Log-normalize catalog popularity so large counts remain bounded."""

        return min(
            1.0,
            math.log1p(max(0, rating_count))
            / math.log1p(self.config.popularity_count_cap),
        )

    @staticmethod
    def _profile_terms(customer_profile: dict) -> frozenset[str]:
        profile_text = " ".join(
            str(value) for value in customer_profile.get("preference_tags", [])
        )
        return frozenset(tokenize(profile_text))
