from __future__ import annotations

import re
from typing import Sequence

from shopping_copilot.indexing.store import CatalogIndex
from shopping_copilot.retrieval.models import RetrievalRequest

TOKEN_RE = re.compile(r"[\w\d]+", re.UNICODE)


def _extract_query_terms(request: RetrievalRequest) -> list[str]:
    """Aggregates all meaningful query terms from the request without duplication."""
    terms: list[str] = []
    # 1. Category
    if request.category:
        terms.extend(TOKEN_RE.findall(request.category))
    # 2. Product terms & residual phrases
    for t in request.product_terms:
        terms.extend(TOKEN_RE.findall(t))
    for p in request.raw_phrases:
        terms.extend(TOKEN_RE.findall(p))
    # 3. Active constraint values
    for c in request.active_constraints:
        for val in c.values:
            terms.extend(TOKEN_RE.findall(val))
    # 4. Non-suppressed profile preferences
    for pref in request.profile_preferences:
        terms.extend(TOKEN_RE.findall(pref))

    # Normalize and deduplicate
    cleaned = [t.lower() for t in terms if len(t) > 1]
    return list(dict.fromkeys(cleaned))


class TitleFTSGenerator:
    """Precision candidate generator querying only product titles."""

    NAME = "title_fts"

    def __init__(self, catalog_index: CatalogIndex) -> None:
        self.catalog_index = catalog_index

    def generate(self, request: RetrievalRequest, limit: int = 100) -> list[tuple[str, float]]:
        terms = _extract_query_terms(request)
        if not terms:
            return []

        # Weights: parent_asin=0, title=10, others=0
        title_weights = (0.0, 10.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        return self.catalog_index.search_bm25(terms, limit=limit, weights=title_weights)


class FieldWeightedFTSGenerator:
    """Recall candidate generator querying all product search fields with BM25 weights."""

    NAME = "field_fts"

    def __init__(self, catalog_index: CatalogIndex) -> None:
        self.catalog_index = catalog_index

    def generate(self, request: RetrievalRequest, limit: int = 200) -> list[tuple[str, float]]:
        terms = _extract_query_terms(request)
        if not terms:
            return []

        return self.catalog_index.search_bm25(terms, limit=limit)
