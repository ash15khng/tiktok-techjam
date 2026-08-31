from __future__ import annotations

import unittest

from submission.src.catalog.models import ProductRecord
from submission.src.catalog.structure import CatalogStructureIndex


def product(
    parent_asin: str,
    *,
    categories: tuple[str, ...],
    features: tuple[str, ...],
    rating_number: int,
) -> ProductRecord:
    return ProductRecord(
        parent_asin=parent_asin,
        title="",
        categories=categories,
        features=features,
        details=(),
        store="",
        description=(),
        price=None,
        average_rating=4.0,
        rating_number=rating_number,
    )


class CatalogStructureIndexTest(unittest.TestCase):
    def setUp(self) -> None:
        records = (
            product(
                "MATCH",
                categories=("Clothing, Shoes & Jewelry", "Men", "Shoes", "Running"),
                features=("waterproof breathable membrane",),
                rating_number=5,
            ),
            product(
                "POPULAR",
                categories=("Clothing, Shoes & Jewelry", "Men", "Shoes", "Running"),
                features=("basic road shoe",),
                rating_number=500,
            ),
            product(
                "OTHER",
                categories=("Clothing, Shoes & Jewelry", "Women", "Jewelry", "Earrings"),
                features=("waterproof breathable membrane",),
                rating_number=5_000,
            ),
        )
        self.index = CatalogStructureIndex(
            {record.parent_asin: record for record in records}
        )

    def test_exact_phrase_outranks_popularity_inside_resolved_bucket(self) -> None:
        ranked = self.index.search(
            ("Shoes Running",),
            ("waterproof breathable membrane",),
            limit=10,
        )

        self.assertEqual([item.parent_asin for item in ranked], ["MATCH", "POPULAR"])

    def test_leaf_suffix_unions_only_matching_category_buckets(self) -> None:
        ranked = self.index.search(("Running",), (), limit=10)

        self.assertEqual(
            {item.parent_asin for item in ranked},
            {"MATCH", "POPULAR"},
        )
        self.assertNotIn("OTHER", {item.parent_asin for item in ranked})

    def test_unresolved_category_returns_empty_for_lexical_fallback(self) -> None:
        self.assertEqual(
            self.index.search(("mystery gadget",), ("waterproof",), limit=10),
            [],
        )


if __name__ == "__main__":
    unittest.main()
