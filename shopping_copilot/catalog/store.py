"""Immutable catalog access and SQLite FTS indexes."""

from __future__ import annotations

import json
import math
import sqlite3
from functools import lru_cache
from pathlib import Path

from shopping_copilot.catalog.models import CatalogSearchResult, ProductRecord
from shopping_copilot.catalog.normalization import flatten_text, string_values, tokenize


FIELD_WEIGHTS = (0.0, 6.0, 4.0, 2.5, 2.5, 1.5, 1.0)
TITLE_WEIGHTS = (0.0, 8.0, 0.4, 0.2, 0.2, 0.2, 0.1)
CATEGORY_WEIGHTS = (0.0, 0.5, 8.0, 0.5, 0.5, 0.2, 0.2)
CONSTRAINT_WEIGHTS = (0.0, 1.5, 0.8, 7.0, 6.0, 0.5, 3.0)


def _number(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


class CatalogStore:
    """Read-only product store; derived indexes never mutate source records."""

    def __init__(self, catalog_path: str | Path) -> None:
        self.catalog_path = Path(catalog_path)
        self.connection = sqlite3.connect(":memory:", check_same_thread=False)
        self.products: dict[str, ProductRecord] = {}
        self._build()
        self.valid_ids = frozenset(self.products)
        self._popular = tuple(
            product.parent_asin
            for product in sorted(
                self.products.values(),
                key=lambda item: (-item.rating_number, -(item.average_rating or 0.0), item.parent_asin),
            )
        )

    def _build(self) -> None:
        cursor = self.connection.cursor()
        cursor.execute(
            "CREATE VIRTUAL TABLE products_fts USING fts5("
            "parent_asin UNINDEXED, title, categories, features, details, store, description, "
            "tokenize='unicode61 remove_diacritics 2')"
        )
        batch: list[tuple[str, str, str, str, str, str, str]] = []
        with self.catalog_path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                raw = json.loads(line)
                parent_asin = str(raw.get("parent_asin") or "").strip()
                if not parent_asin:
                    raise ValueError(f"catalog line {line_number} has no parent_asin")
                if parent_asin in self.products:
                    raise ValueError(f"duplicate parent_asin: {parent_asin}")
                product = ProductRecord(
                    parent_asin=parent_asin,
                    title=flatten_text(raw.get("title")),
                    categories=string_values(raw.get("categories")),
                    features=string_values(raw.get("features")),
                    details=string_values(raw.get("details")),
                    store=flatten_text(raw.get("store")),
                    description=string_values(raw.get("description")),
                    price=_number(raw.get("price")),
                    average_rating=_number(raw.get("average_rating")),
                    rating_number=int(_number(raw.get("rating_number")) or 0),
                )
                self.products[parent_asin] = product
                batch.append(
                    (
                        parent_asin,
                        product.title,
                        " ".join(product.categories),
                        " ".join(product.features),
                        " ".join(product.details),
                        product.store,
                        " ".join(product.description),
                    )
                )
                if len(batch) >= 1000:
                    cursor.executemany("INSERT INTO products_fts VALUES (?, ?, ?, ?, ?, ?, ?)", batch)
                    batch.clear()
        if batch:
            cursor.executemany("INSERT INTO products_fts VALUES (?, ?, ?, ?, ?, ?, ?)", batch)
        cursor.execute("CREATE VIRTUAL TABLE products_vocab USING fts5vocab(products_fts, 'row')")
        self.connection.commit()

    def __len__(self) -> int:
        return len(self.products)

    def get(self, parent_asin: str) -> ProductRecord:
        return self.products[parent_asin]

    def popular(self, limit: int) -> tuple[str, ...]:
        return self._popular[: max(0, limit)]

    def document_frequencies(self, terms: tuple[str, ...]) -> dict[str, int]:
        unique = tuple(dict.fromkeys(terms))
        if not unique:
            return {}
        placeholders = ",".join("?" for _ in unique)
        rows = self.connection.execute(
            f"SELECT term, doc FROM products_vocab WHERE term IN ({placeholders})",
            unique,
        ).fetchall()
        return {str(term): int(document_count) for term, document_count in rows}

    def rare_terms(self, terms: tuple[str, ...], limit: int) -> tuple[str, ...]:
        unique = tuple(dict.fromkeys(terms))
        frequencies = self.document_frequencies(unique)
        return tuple(
            sorted(unique, key=lambda term: (frequencies.get(term, len(self) + 1), unique.index(term)))[:limit]
        )

    def inverse_document_frequency(self, terms: tuple[str, ...]) -> dict[str, float]:
        frequencies = self.document_frequencies(tuple(dict.fromkeys(terms)))
        return {
            term: math.log((len(self) + 1) / (frequencies.get(term, len(self)) + 1)) + 1.0
            for term in dict.fromkeys(terms)
        }

    def search(
        self,
        terms: tuple[str, ...],
        *,
        weights: tuple[float, ...],
        limit: int,
        require_all: bool = False,
    ) -> list[CatalogSearchResult]:
        unique = tuple(dict.fromkeys(token for token in terms if token))
        if not unique or limit <= 0:
            return []
        operator = " AND " if require_all else " OR "
        expression = operator.join(f'"{term}"' for term in unique)
        weight_sql = ", ".join(str(float(value)) for value in weights)
        try:
            rows = self.connection.execute(
                "SELECT parent_asin, "
                f"bm25(products_fts, {weight_sql}) AS score "
                "FROM products_fts WHERE products_fts MATCH ? "
                "ORDER BY score, parent_asin LIMIT ?",
                (expression, int(limit)),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [CatalogSearchResult(str(parent_asin), float(score)) for parent_asin, score in rows]

    @lru_cache(maxsize=4096)
    def product_terms(self, parent_asin: str) -> frozenset[str]:
        return frozenset(tokenize(self.products[parent_asin].search_text))

    @lru_cache(maxsize=4096)
    def product_token_text(self, parent_asin: str) -> str:
        return " ".join(tokenize(self.products[parent_asin].search_text, drop_stopwords=False))
