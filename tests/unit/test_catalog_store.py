from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from submission.src.catalog.store import FIELD_WEIGHTS, CatalogStore


class CatalogStoreTest(unittest.TestCase):
    def test_search_cache_returns_isolated_lists_with_identical_order(self) -> None:
        products = (
            {"parent_asin": "A", "title": "Red running shoe", "rating_number": 5},
            {"parent_asin": "B", "title": "Blue walking shoe", "rating_number": 3},
        )
        with tempfile.TemporaryDirectory() as directory:
            catalog_path = Path(directory) / "catalog.jsonl"
            catalog_path.write_text(
                "".join(json.dumps(product) + "\n" for product in products),
                encoding="utf-8",
            )
            store = CatalogStore(catalog_path)

            first = store.search(("shoe",), weights=FIELD_WEIGHTS, limit=10)
            second = store.search(("shoe",), weights=FIELD_WEIGHTS, limit=10)

            self.assertEqual(first, second)
            self.assertIsNot(first, second)
            first.clear()
            self.assertEqual([item.parent_asin for item in second], ["A", "B"])
            self.assertEqual(store.cache_diagnostics()["search"]["hits"], 1)
            self.assertEqual(store.cache_diagnostics()["search"]["misses"], 1)


if __name__ == "__main__":
    unittest.main()
