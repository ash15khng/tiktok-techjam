from __future__ import annotations

import time
import unittest
from pathlib import Path

from shopping_copilot.catalog.loader import CatalogLoader
from shopping_copilot.indexing.store import CatalogIndex
from shopping_copilot.understanding.models import Attribute


class TestCatalogIndexingIntegration(unittest.TestCase):
    CATALOG_PATH = Path("data/catalog.jsonl")

    @unittest.skipUnless(CATALOG_PATH.is_file(), "data/catalog.jsonl is required for integration test")
    def test_full_catalog_ingestion_and_query_performance(self) -> None:
        start_time = time.perf_counter()
        loader = CatalogLoader()
        index = CatalogIndex()

        # Load first 1,000 products for quick integration testing
        records_slice = []
        for i, record in enumerate(loader.stream_file(self.CATALOG_PATH)):
            records_slice.append(record)
            if i >= 999:
                break

        index.build_from_records(records_slice)
        load_duration = time.perf_counter() - start_time

        self.assertEqual(index.total_products, 1000)
        self.assertLess(load_duration, 3.0, f"Loading 1000 records took {load_duration:.2f}s, expected < 3.0s")

        # Test BM25 query latency
        q_start = time.perf_counter()
        bm25_results = index.search_bm25("black leather boots", limit=10)
        q_duration = (time.perf_counter() - q_start) * 1000.0  # ms

        self.assertLess(q_duration, 20.0, f"BM25 query took {q_duration:.2f}ms, expected < 20.0ms")

        # Test attribute filter
        black_items = index.filter_by_attribute(Attribute.COLOR, "black")
        self.assertTrue(isinstance(black_items, frozenset))

        # Test price filter
        budget_items = index.filter_by_price(max_price=50.00)
        self.assertTrue(isinstance(budget_items, frozenset))

        # Test vocabulary generation
        vocab = index.get_vocabulary_by_attribute()
        self.assertIn(Attribute.COLOR, vocab)
        self.assertIn(Attribute.MATERIAL, vocab)


if __name__ == "__main__":
    unittest.main()
