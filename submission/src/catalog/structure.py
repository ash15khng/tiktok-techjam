"""Catalog-derived category structure and bounded structural retrieval.

Inputs are immutable :class:`ProductRecord` values plus the current category
and positive preference phrases. The index never reads labels or evaluator
state. It returns a ranked catalog-ID list from a resolved category bucket, or
an empty list when resolution is unsafe so the lexical ensemble remains the
complete fallback.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Callable

from submission.src.catalog.models import CatalogSearchResult, ProductRecord
from submission.src.catalog.normalization import tokenize


GENERIC_CATEGORY_KEYS = frozenset(
    {
        "clothing",
        "clothing shoes jewelry",
    }
)


def _token_text(value: str) -> str:
    """Normalize punctuation and spacing into a comparable token sequence."""

    return " ".join(tokenize(value, drop_stopwords=False))


def _category_key(categories: tuple[str, ...]) -> str:
    """Return a product's two most specific non-generic category segments."""

    segments: list[str] = []
    for value in categories:
        for part in str(value).split(","):
            normalized = _token_text(part)
            if normalized and normalized not in GENERIC_CATEGORY_KEYS:
                segments.append(normalized)
    return " ".join(segments[-2:]) if segments else ""


class CatalogStructureIndex:
    """Resolve conservative category buckets and rank their members.

    The index stores each catalog ID once in a category bucket. The production
    store supplies its bounded shared token cache, avoiding a second normalized
    copy and the much larger eager attribute-postings alternative.
    """

    def __init__(
        self,
        products: dict[str, ProductRecord],
        *,
        token_view: Callable[[str], tuple[str, frozenset[str]]] | None = None,
    ) -> None:
        self.products = products
        self._token_view = token_view or self._default_token_view
        buckets: dict[str, list[str]] = defaultdict(list)
        for product in products.values():
            key = _category_key(product.categories)
            if key:
                buckets[key].append(product.parent_asin)

        def popularity_key(parent_asin: str) -> tuple[int, float, str]:
            product = products[parent_asin]
            return (
                -product.rating_number,
                -(product.average_rating or 0.0),
                parent_asin,
            )

        self._buckets = {
            key: tuple(sorted(members, key=popularity_key))
            for key, members in buckets.items()
        }
        suffix_keys: dict[str, list[str]] = defaultdict(list)
        for key in self._buckets:
            words = key.split()
            for start in range(len(words)):
                suffix_keys[" ".join(words[start:])].append(key)
        self._suffix_keys = {
            suffix: tuple(keys) for suffix, keys in suffix_keys.items()
        }

    def search(
        self,
        category_phrases: tuple[str, ...],
        preference_phrases: tuple[str, ...],
        *,
        limit: int,
    ) -> list[CatalogSearchResult]:
        """Rank a safely resolved category bucket by disclosed evidence.

        Exact normalized phrase coverage is considered before token coverage
        and catalog popularity. This gives long catalog-native phrases their
        deserved precision without excluding products whose metadata is
        missing. An unresolved category returns ``[]`` rather than guessing.
        """

        if limit <= 0:
            return []
        members = self._resolve_members(category_phrases)
        if not members:
            return []
        phrases = tuple(
            dict.fromkeys(
                normalized
                for phrase in preference_phrases
                if (normalized := _token_text(phrase))
            )
        )
        phrase_terms = tuple(
            frozenset(tokenize(phrase)) for phrase in preference_phrases
        )
        all_terms = frozenset(term for terms in phrase_terms for term in terms)
        denominator = max(1, len(all_terms))

        ranked: list[tuple[int, float, float, str]] = []
        for parent_asin in members:
            product_text, product_terms = self._token_view(parent_asin)
            exact_count = sum(phrase in product_text for phrase in phrases)
            coverage = len(all_terms & product_terms) / denominator
            product = self.products[parent_asin]
            popularity = math.log1p(max(0, product.rating_number))
            ranked.append((exact_count, coverage, popularity, parent_asin))

        ranked.sort(
            key=lambda item: (-item[0], -item[1], -item[2], item[3])
        )
        return [
            CatalogSearchResult(
                parent_asin=item[3],
                raw_score=-(item[0] + item[1]),
            )
            for item in ranked[:limit]
        ]

    def _resolve_members(
        self,
        category_phrases: tuple[str, ...],
    ) -> tuple[str, ...]:
        """Resolve exact, contained, or exact-suffix category evidence."""

        for phrase in reversed(category_phrases):
            query = _token_text(phrase)
            if not query:
                continue
            direct = self._buckets.get(query)
            if direct:
                return direct

            padded_query = f" {query} "
            contained = [
                key
                for key in self._buckets
                if f" {key} " in padded_query or padded_query in f" {key} "
            ]
            if contained:
                most_specific = max(len(key.split()) for key in contained)
                return self._merge_members(
                    key for key in contained if len(key.split()) == most_specific
                )

            suffix_matches = self._suffix_keys.get(query)
            if suffix_matches:
                return self._merge_members(suffix_matches)
        return ()

    def _merge_members(self, keys) -> tuple[str, ...]:
        """Merge multiple safe buckets in the same popularity order."""

        members = {
            parent_asin
            for key in keys
            for parent_asin in self._buckets.get(key, ())
        }
        return tuple(
            sorted(
                members,
                key=lambda parent_asin: (
                    -self.products[parent_asin].rating_number,
                    -(self.products[parent_asin].average_rating or 0.0),
                    parent_asin,
                ),
            )
        )

    def _default_token_view(self, parent_asin: str) -> tuple[str, frozenset[str]]:
        """Return a standalone view when no store cache is supplied."""

        product = self.products[parent_asin]
        return (
            _token_text(product.search_text),
            frozenset(tokenize(product.search_text)),
        )
