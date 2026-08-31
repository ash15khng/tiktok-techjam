"""Typed, normalized records shared by catalog and retrieval components."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProductRecord:
    """One immutable frozen-catalog parent product.

    Missing text fields are empty strings/tuples and missing numeric values are
    ``None``. ``rating_number`` alone defaults to zero because it is a count.
    """

    parent_asin: str
    title: str
    categories: tuple[str, ...]
    features: tuple[str, ...]
    details: tuple[str, ...]
    store: str
    description: tuple[str, ...]
    price: float | None
    average_rating: float | None
    rating_number: int
    detail_pairs: tuple[tuple[str, str], ...] = ()

    @property
    def search_text(self) -> str:
        """Return all participant-visible text in indexable field order."""

        return " ".join(
            (
                self.title,
                *self.categories,
                *self.features,
                *self.details,
                self.store,
                *self.description,
            )
        )


@dataclass(frozen=True)
class CatalogSearchResult:
    """One ordered lexical result with its raw SQLite BM25 score."""

    parent_asin: str
    raw_score: float
