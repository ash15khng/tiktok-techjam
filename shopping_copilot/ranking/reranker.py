"""Inspectable deterministic reranking with an optional semantic stage."""

from __future__ import annotations

from shopping_copilot.catalog.normalization import tokenize
from shopping_copilot.catalog.store import CatalogStore
from shopping_copilot.config import MVPConfig
from shopping_copilot.dialog.models import ActiveState
from shopping_copilot.retrieval.models import CandidateEvidence


class LightweightReranker:
    def __init__(self, store: CatalogStore, config: MVPConfig) -> None:
        self.store = store
        self.config = config

    def rank(
        self,
        candidates: list[CandidateEvidence],
        active: ActiveState,
        customer_profile: dict,
    ) -> list[CandidateEvidence]:
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
            profile_score = min(self.config.profile_score_cap, 0.03 * profile_overlap)
            candidate.final_score = (
                0.52 * (candidate.rrf_score / max_rrf)
                + 0.36 * coverage
                + 0.12 * exact_ratio
                + profile_score
                - (0.70 if contradiction else 0.0)
            )
        rerankable.sort(key=lambda item: (-item.final_score, -item.rrf_score, item.parent_asin))
        return [*rerankable, *remainder]
