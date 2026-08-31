"""
Load frozen JSONL products and expose read-only SQLite FTS5 search.

The input file contains one product object per line.
``CatalogStore`` validates unique non-empty ``parent_asin`` values,
normalizes missing fields to defaults, and builds only in-memory derived indexes;
"""

from __future__ import annotations

import json
import math
import sqlite3
from functools import lru_cache
from pathlib import Path

from submission.src.catalog.attributes import CatalogAttributeRegistry
from submission.src.catalog.models import CatalogSearchResult, ProductRecord
from submission.src.catalog.normalization import (
    STOPWORDS,
    flatten_text,
    string_values,
    tokenize,
)
from submission.src.catalog.structure import CatalogStructureIndex


# SQLite BM25 weights: 
# parent_asin, title, categories, features, details, store, description. 
# Raising a field makes matches there more influential
FIELD_WEIGHTS = (0.0, 6.0, 4.0, 2.5, 2.5, 1.5, 1.0)
TITLE_WEIGHTS = (0.0, 8.0, 0.4, 0.2, 0.2, 0.2, 0.1)
CATEGORY_WEIGHTS = (0.0, 0.5, 8.0, 0.5, 0.5, 0.2, 0.2)
CONSTRAINT_WEIGHTS = (0.0, 1.5, 0.8, 7.0, 6.0, 0.5, 3.0)
CATALOG_INSERT_BATCH_SIZE = 1_000
PRODUCT_TEXT_CACHE_SIZE = 4_096
# Cached searches remove repeated category/title work across later turns and
# common customer requests. Raising this improves reuse but retains more result
# objects; lowering it reduces memory but repeats SQLite work. The 256-entry
# setting produced 901 hits and 809 misses on the 200-session public replay.
SEARCH_CACHE_SIZE = 256


def _number(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


class CatalogStore:
    """Read-only product store with in-memory SQLite FTS5 search and derived indexes."""

    def __init__(self, catalog_path: str | Path) -> None:
        self.catalog_path = Path(catalog_path)
        self.connection = sqlite3.connect(":memory:", check_same_thread=False)
        self.products: dict[str, ProductRecord] = {}
        # Construct caches per store. Decorating these methods at class scope
        # would share counters and retain old CatalogStore instances as keys.
        self._search_cached = lru_cache(maxsize=SEARCH_CACHE_SIZE)(
            self._search_uncached
        )
        self._product_token_view_cached = lru_cache(
            maxsize=PRODUCT_TEXT_CACHE_SIZE
        )(self._product_token_view_uncached)
        self._build()
        self.valid_ids = frozenset(self.products)
        self.attributes = CatalogAttributeRegistry(self.products)
        self._structure: CatalogStructureIndex | None = None
        self._popular = tuple(
            product.parent_asin
            for product in sorted(
                self.products.values(),
                key=lambda item: (
                    -item.rating_number,
                    -(item.average_rating or 0.0),
                    item.parent_asin,
                ),
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
                    detail_pairs=tuple(
                        (str(key), flatten_text(value))
                        for key, value in (raw.get("details") or {}).items()
                    ) if isinstance(raw.get("details"), dict) else (),
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
                if len(batch) >= CATALOG_INSERT_BATCH_SIZE:
                    cursor.executemany(
                        "INSERT INTO products_fts VALUES (?, ?, ?, ?, ?, ?, ?)",
                        batch,
                    )
                    batch.clear()
        if batch:
            cursor.executemany(
                "INSERT INTO products_fts VALUES (?, ?, ?, ?, ?, ?, ?)",
                batch,
            )
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
            sorted(
                unique,
                key=lambda term: (
                    frequencies.get(term, len(self) + 1),
                    unique.index(term),
                ),
            )[:limit]
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
        """
        Returns ordered FTS matches for normalized terms.

        ``require_all=True`` uses AND semantics; otherwise OR preserves recall.
        SQLite parser failures yield an empty route so other generators and the
        response guard can continue safely.
        """

        unique = tuple(dict.fromkeys(token for token in terms if token))
        if not unique or limit <= 0:
            return []
        return list(
            self._search_cached(
                unique,
                tuple(float(value) for value in weights),
                int(limit),
                bool(require_all),
            )
        )

    def _search_uncached(
        self,
        unique: tuple[str, ...],
        weights: tuple[float, ...],
        limit: int,
        require_all: bool,
    ) -> tuple[CatalogSearchResult, ...]:
        """Execute one immutable FTS query and cache its ordered result."""

        operator = " AND " if require_all else " OR "
        expression = operator.join(f'"{term}"' for term in unique)
        weight_sql = ", ".join(str(value) for value in weights)
        try:
            rows = self.connection.execute(
                "SELECT parent_asin, "
                f"bm25(products_fts, {weight_sql}) AS score "
                "FROM products_fts WHERE products_fts MATCH ? "
                "ORDER BY score, parent_asin LIMIT ?",
                (expression, int(limit)),
            ).fetchall()
        except sqlite3.OperationalError:
            return ()
        return tuple(
            CatalogSearchResult(str(parent_asin), float(score))
            for parent_asin, score in rows
        )

    def structural_search(
        self,
        category_phrases: tuple[str, ...],
        preference_phrases: tuple[str, ...],
        *,
        limit: int,
    ) -> list[CatalogSearchResult]:
        """Return one catalog-structural route or ``[]`` when unresolved."""

        return self.prepare_structure().search(
            category_phrases,
            preference_phrases,
            limit=limit,
        )

    def prepare_structure(self) -> CatalogStructureIndex:
        """Build the optional structural index once and return it.

        Disabled configurations avoid this startup and memory cost. Enabled
        configurations call this during agent construction so the first
        customer turn does not absorb lazy-index latency.
        """

        if self._structure is None:
            self._structure = CatalogStructureIndex(
                self.products,
                token_view=self.product_token_view,
            )
        return self._structure

    def product_token_view(self, parent_asin: str) -> tuple[str, frozenset[str]]:
        """Return phrase and set views from one shared tokenization pass."""

        return self._product_token_view_cached(parent_asin)

    def _product_token_view_uncached(
        self,
        parent_asin: str,
    ) -> tuple[str, frozenset[str]]:
        """Build normalized phrase and term views for one catalog product."""

        all_tokens = tokenize(
            self.products[parent_asin].search_text,
            drop_stopwords=False,
        )
        terms = frozenset(
            token
            for token in all_tokens
            if (len(token) > 1 or token.isdigit()) and token not in STOPWORDS
        )
        return " ".join(all_tokens), terms

    def product_terms(self, parent_asin: str) -> frozenset[str]:
        return self.product_token_view(parent_asin)[1]

    def product_token_text(self, parent_asin: str) -> str:
        return self.product_token_view(parent_asin)[0]

    def cache_diagnostics(self) -> dict[str, dict[str, int | None]]:
        """Return aggregate cache counters without query or product content."""

        return {
            "search": self._search_cached.cache_info()._asdict(),
            "product_token_view": (
                self._product_token_view_cached.cache_info()._asdict()
            ),
        }
