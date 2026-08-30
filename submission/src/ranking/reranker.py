"""Inspectable deterministic reranking with an optional semantic stage."""

from __future__ import annotations

import math

from submission.src.catalog.normalization import tokenize
from submission.src.catalog.store import CatalogStore
from submission.src.config import AgentConfig
from submission.src.dialog.models import ActiveState
from submission.src.ranking.budget import price_signal
from submission.src.retrieval.models import CandidateEvidence


class LightweightReranker:
    """Apply inspectable evidence signals to a bounded fused candidate union."""

    def __init__(self, store: CatalogStore, config: AgentConfig) -> None:
        self.store = store
        self.config = config

    def rank(
        self,
        candidates: list[CandidateEvidence],
        active: ActiveState,
        customer_profile: dict,
    ) -> list[CandidateEvidence]:
        """Return candidates ordered best-to-worst for the active request."""

        if not candidates:
            return []
        query_terms = active.query_terms()
        idf = self.store.inverse_document_frequency(query_terms)
        denominator = sum(idf.values()) or 1.0
        max_rrf = max(item.rrf_score for item in candidates) or 1.0
        phrases = [tuple(tokenize(value, drop_stopwords=False)) for value in active.preference_phrases]
        exclusion_terms = [set(tokenize(value)) for value in active.exclusions]
        profile_terms = set(tokenize(" ".join(str(value) for value in customer_profile.get("preference_tags", []))))

        rerankable = candidates[: self.config.rerank_depth]
        remainder = candidates[self.config.rerank_depth :]
        for candidate in rerankable:
            product_terms = self.store.product_terms(candidate.parent_asin)
            coverage = sum(weight for term, weight in idf.items() if term in product_terms) / denominator
            product_token_text = self.store.product_token_text(candidate.parent_asin)
            exact_count = sum(
                int(bool(phrase) and " ".join(phrase) in product_token_text)
                for phrase in phrases
            )
            exact_ratio = exact_count / max(1, len(phrases))
            contradiction = any(values and values.issubset(product_terms) for values in exclusion_terms)
            profile_overlap = len(product_terms & profile_terms) / max(1, len(profile_terms))
            profile_score = self.config.profile_score_cap * min(1.0, profile_overlap)
            product = self.store.get(candidate.parent_asin)
            rating_count = product.rating_number
            budget_signal = price_signal(product.price, active.slot_values.get("budget", []))
            popularity = min(
                1.0,
                math.log1p(max(0, rating_count)) / math.log1p(self.config.popularity_count_cap),
            )
            candidate.final_score = (
                self.config.rerank_rrf_weight * (candidate.rrf_score / max_rrf)
                + self.config.rerank_idf_coverage_weight * coverage
                + self.config.rerank_exact_phrase_weight * exact_ratio
                + profile_score
                + self.config.popularity_weight * popularity
                + self.config.budget_signal_weight * budget_signal
                - (self.config.exclusion_penalty if contradiction else 0.0)
            )
        rerankable.sort(key=lambda item: (-item.final_score, -item.rrf_score, item.parent_asin))
        return [*rerankable, *remainder]
