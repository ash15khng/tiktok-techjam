from __future__ import annotations

import bisect
import math
import re
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from shopping_copilot.catalog.extraction import clean_attribute_value, normalize_str
from shopping_copilot.catalog.loader import CatalogLoader
from shopping_copilot.catalog.models import ProductRecord
from shopping_copilot.indexing.schema import (
    CREATE_PRODUCTS_FTS_SQL,
    CREATE_PRODUCTS_VOCAB_SQL,
    DEFAULT_BM25_FIELD_WEIGHTS,
    MAX_FTS_QUERY_TERMS,
)
from shopping_copilot.understanding.models import Attribute

TOKEN_CLEAN_RE = re.compile(r"[^\w\d\s]", re.UNICODE)
QUERY_TOKEN_RE = re.compile(r"[\w\d]+", re.UNICODE)


class CatalogIndex:
    """In-memory multi-faceted catalog index combining SQLite FTS5 and posting sets."""

    def __init__(self, connection: sqlite3.Connection | None = None) -> None:
        self.connection = connection or sqlite3.connect(":memory:")
        self._products: dict[str, ProductRecord] = {}
        self._category_to_ids: dict[str, set[str]] = defaultdict(set)
        self._attribute_to_ids: dict[Attribute, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        self._sorted_prices: list[tuple[float, str]] = []  # (price, asin)
        self._asins_without_price: set[str] = set()
        self._doc_frequencies: dict[str, int] = {}
        self._total_docs: int = 0
        self._is_indexed: bool = False

    @property
    def total_products(self) -> int:
        return len(self._products)

    def get_product(self, parent_asin: str) -> ProductRecord | None:
        """Retrieves a product record by its canonical ASIN."""
        return self._products.get(parent_asin)

    def build_from_records(self, records: Iterable[ProductRecord]) -> None:
        """Populates in-memory database and inverted indices from ProductRecord stream."""
        cursor = self.connection.cursor()
        cursor.execute(CREATE_PRODUCTS_FTS_SQL)

        fts_batch: list[tuple[str, str, str, str, str, str, str]] = []
        valid_prices: list[tuple[float, str]] = []

        for record in records:
            asin = record.parent_asin
            self._products[asin] = record

            # Inverted category index
            for cat in record.categories:
                cat_clean = clean_attribute_value(cat)
                if cat_clean:
                    self._category_to_ids[cat_clean].add(asin)

            # Inverted attribute index
            for attr_name, val_set in record.attributes.items():
                try:
                    attr_enum = Attribute(attr_name)
                except ValueError:
                    attr_enum = Attribute.OTHER

                for val in val_set:
                    val_clean = clean_attribute_value(val)
                    if val_clean:
                        self._attribute_to_ids[attr_enum][val_clean].add(asin)

            # Price indexing
            if record.price.lower is not None:
                valid_prices.append((record.price.lower, asin))
            else:
                self._asins_without_price.add(asin)

            # Prepare FTS batch
            sf = record.search_fields
            fts_batch.append((
                asin,
                sf.get("title", ""),
                sf.get("categories", ""),
                sf.get("features", ""),
                sf.get("details", ""),
                sf.get("store", ""),
                sf.get("description", ""),
            ))

        # Insert batch into SQLite FTS5
        cursor.executemany(
            "INSERT INTO products(parent_asin, title, categories, features, details, store, description) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            fts_batch,
        )

        # Build vocabulary table for IDF calculation
        cursor.execute(CREATE_PRODUCTS_VOCAB_SQL)
        cursor.execute("SELECT term, doc FROM products_vocab")
        for term, doc_freq in cursor.fetchall():
            self._doc_frequencies[term] = int(doc_freq)

        # Sort price index
        valid_prices.sort(key=lambda item: item[0])
        self._sorted_prices = valid_prices
        self._total_docs = len(self._products)
        self._is_indexed = True

    @classmethod
    def load_from_file(cls, catalog_path: str | Path) -> CatalogIndex:
        """Loads and indexes a catalog JSONL file into memory."""
        loader = CatalogLoader()
        index = cls()
        index.build_from_records(loader.stream_file(catalog_path))
        return index

    def compute_idf(self, term: str) -> float:
        """Calculates Lucene/BM25 IDF for a single term."""
        df = self._doc_frequencies.get(term.lower(), 0)
        n = self._total_docs
        if n == 0 or df == 0:
            return 0.0
        return math.log(1.0 + (n - df + 0.5) / (df + 0.5))

    def prune_query_terms(self, terms: Sequence[str], max_terms: int = MAX_FTS_QUERY_TERMS) -> list[str]:
        """Prunes query terms to the most discriminative terms ranked by descending IDF."""
        cleaned_terms: list[str] = []
        for t in terms:
            for tok in QUERY_TOKEN_RE.findall(t.lower()):
                if len(tok) > 1:
                    cleaned_terms.append(tok)

        # Remove duplicates while preserving order
        unique_terms = list(dict.fromkeys(cleaned_terms))
        if len(unique_terms) <= max_terms:
            return unique_terms

        # Rank by IDF descending
        ranked = sorted(unique_terms, key=lambda t: self.compute_idf(t), reverse=True)
        return ranked[:max_terms]

    def search_bm25(
        self,
        query_terms: Sequence[str] | str,
        limit: int = 50,
        weights: tuple[float, ...] | None = None,
    ) -> list[tuple[str, float]]:
        """Executes field-weighted BM25 lexical search using SQLite FTS5."""
        if not self._is_indexed or self._total_docs == 0:
            return []

        if isinstance(query_terms, str):
            terms = QUERY_TOKEN_RE.findall(query_terms)
        else:
            terms = list(query_terms)

        pruned = self.prune_query_terms(terms)
        if not pruned:
            return []

        fts_query = " OR ".join(f'"{t}"' for t in pruned)
        w = weights or DEFAULT_BM25_FIELD_WEIGHTS
        sql = (
            f"SELECT parent_asin, -bm25(products, {w[0]}, {w[1]}, {w[2]}, {w[3]}, {w[4]}, {w[5]}, {w[6]}) AS score "
            f"FROM products WHERE products MATCH ? ORDER BY score DESC LIMIT ?"
        )
        cursor = self.connection.cursor()
        try:
            cursor.execute(sql, (fts_query, limit))
            return [(str(row[0]), float(row[1])) for row in cursor.fetchall()]
        except sqlite3.OperationalError:
            return []

    def filter_by_category(self, category: str) -> frozenset[str]:
        """Returns ASINs matching the given category (exact or substring)."""
        cat_norm = clean_attribute_value(category)
        if not cat_norm:
            return frozenset()

        # Exact match
        if cat_norm in self._category_to_ids:
            return frozenset(self._category_to_ids[cat_norm])

        # Substring / partial match
        matching_asins: set[str] = set()
        for c, asins in self._category_to_ids.items():
            if cat_norm in c or c in cat_norm:
                matching_asins.update(asins)
        return frozenset(matching_asins)

    def filter_by_attribute(self, attribute: Attribute, value: str) -> frozenset[str]:
        """Returns ASINs possessing the specific attribute value."""
        val_norm = clean_attribute_value(value)
        if not val_norm:
            return frozenset()

        attr_map = self._attribute_to_ids.get(attribute, {})
        if val_norm in attr_map:
            return frozenset(attr_map[val_norm])

        # Substring match within attribute values
        matching_asins: set[str] = set()
        for v, asins in attr_map.items():
            if val_norm in v or v in val_norm:
                matching_asins.update(asins)
        return frozenset(matching_asins)

    def filter_by_price(
        self,
        min_price: float | None = None,
        max_price: float | None = None,
        include_unknown: bool = True,
    ) -> frozenset[str]:
        """Returns ASINs within the specified price range using binary search."""
        if not self._sorted_prices:
            return frozenset(self._asins_without_price) if include_unknown else frozenset()

        prices_only = [item[0] for item in self._sorted_prices]

        # Bisect lower index
        if min_price is not None:
            left_idx = bisect.bisect_left(prices_only, min_price)
        else:
            left_idx = 0

        # Bisect upper index
        if max_price is not None:
            right_idx = bisect.bisect_right(prices_only, max_price)
        else:
            right_idx = len(self._sorted_prices)

        matching_asins = {self._sorted_prices[i][1] for i in range(left_idx, right_idx)}
        if include_unknown:
            matching_asins.update(self._asins_without_price)

        return frozenset(matching_asins)

    def filter_by_exclusion(self, attribute: Attribute, value: str) -> frozenset[str]:
        """Returns all ASINs that DO NOT contain the specified attribute value."""
        excluded_asins = self.filter_by_attribute(attribute, value)
        all_asins = set(self._products.keys())
        return frozenset(all_asins - excluded_asins)

    def get_vocabulary_by_attribute(self) -> dict[Attribute, set[str]]:
        """Returns canonical vocabulary sets for each Attribute to ground understanding models."""
        vocab: dict[Attribute, set[str]] = defaultdict(set)
        for attr, val_map in self._attribute_to_ids.items():
            vocab[attr].update(val_map.keys())
        return dict(vocab)
