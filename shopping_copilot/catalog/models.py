"""Catalog domain models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProductRecord:
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

    @property
    def search_text(self) -> str:
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
    parent_asin: str
    raw_score: float
