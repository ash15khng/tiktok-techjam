from __future__ import annotations

import re
from typing import Sequence

from shopping_copilot.indexing.store import CatalogIndex
from shopping_copilot.retrieval.models import RetrievalRequest

TOKEN_RE = re.compile(r"[\w\d]+", re.UNICODE)


CONVERSATIONAL_STOPWORDS = frozenset([
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are",
    "aren't", "as", "at", "be", "because", "been", "before", "being", "below", "between", "both",
    "but", "by", "can't", "cannot", "could", "couldn't", "did", "didn't", "do", "does", "doesn't",
    "doing", "don't", "dont", "down", "during", "each", "few", "for", "from", "further", "had",
    "hadn't", "has", "hasn't", "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her",
    "here", "here's", "hers", "herself", "him", "himself", "his", "how", "how's", "i", "i'd",
    "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it", "it's", "its", "itself", "let's",
    "me", "more", "most", "mustn't", "my", "myself", "no", "nor", "not", "of", "off", "on", "once",
    "only", "or", "other", "ought", "our", "ours", "ourselves", "out", "over", "own", "same", "shan't",
    "she", "she'd", "she'll", "she's", "should", "shouldn't", "so", "some", "such", "than", "that",
    "that's", "the", "their", "theirs", "them", "themselves", "then", "there", "there's", "these",
    "they", "they'd", "they'll", "they're", "they've", "this", "those", "through", "to", "too",
    "under", "until", "up", "very", "was", "wasn't", "we", "we'd", "we'll", "we're", "we've", "were",
    "weren't", "what", "what's", "when", "when's", "where", "where's", "which", "while", "who",
    "who's", "whom", "why", "why's", "with", "won't", "would", "wouldn't", "you", "you'd", "you'll",
    "you're", "you've", "your", "yours", "yourself", "yourselves",
    # Conversational domain fillers & simulator meta-tokens
    "looking", "look", "search", "searching", "find", "finding", "want", "wanted", "wants", "need",
    "needed", "needs", "prefer", "preferred", "preference", "preferences", "options", "quite", "right",
    "yet", "specific", "attribute", "attributes", "additional", "exploring", "explore", "judgment",
    "matters", "matter", "something", "anything", "please", "item", "items", "product", "products",
])


def _extract_query_terms(request: RetrievalRequest) -> list[str]:
    """Aggregates all meaningful query terms from the request without duplication and without stopwords."""
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

    # Normalize, filter stopwords, and deduplicate
    cleaned = [
        t.lower() for t in terms
        if len(t) > 1 and t.lower() not in CONVERSATIONAL_STOPWORDS and not (t.isdigit() and len(t) < 3)
    ]
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

