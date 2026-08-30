from __future__ import annotations

import unittest
from shopping_copilot.catalog.models import PriceValue, ProductRecord
from shopping_copilot.indexing.store import CatalogIndex
from shopping_copilot.understanding.models import Attribute


def _make_record(
    parent_asin: str,
    title: str,
    categories: list[str],
    attributes: dict[str, set[str]],
    price_val: float | None = None,
    store: str = "",
    features: str = "",
    description: str = "",
) -> ProductRecord:
    price = PriceValue(lower=price_val, upper=price_val, kind="exact" if price_val is not None else "unknown")
    search_fields = {
        "title": title.lower(),
        "categories": " ".join(categories).lower(),
        "features": features.lower(),
        "details": "",
        "store": store.lower(),
        "description": description.lower(),
    }
    return ProductRecord(
        parent_asin=parent_asin,
        raw={"parent_asin": parent_asin, "title": title},
        search_fields=search_fields,
        categories=tuple(categories),
        attributes={k: frozenset(v) for k, v in attributes.items()},
        attribute_evidence={},
        price=price,
        average_rating=4.5,
        rating_number=50,
        field_presence=frozenset(["title", "categories"]),
    )


class TestCatalogIndex(unittest.TestCase):
    def setUp(self) -> None:
        self.records = [
            _make_record(
                parent_asin="B001",
                title="Men's Vintage Leather Moto Jacket",
                categories=["Clothing, Shoes & Jewelry", "Men", "Jackets"],
                attributes={"material": {"leather"}, "color": {"black"}, "style": {"vintage", "moto"}, "brand": {"schott"}},
                price_val=250.00,
                store="Schott NYC",
                features="100% genuine cowhide leather, heavy duty zipper",
            ),
            _make_record(
                parent_asin="B002",
                title="Women's Lightweight Running Shoes",
                categories=["Clothing, Shoes & Jewelry", "Women", "Shoes"],
                attributes={"material": {"mesh"}, "color": {"white", "blue"}, "style": {"athletic"}, "brand": {"nike"}},
                price_val=75.00,
                store="Nike",
                features="Breathable mesh, cushioned foam midsole",
            ),
            _make_record(
                parent_asin="B003",
                title="Cotton Crewneck Casual T-Shirt",
                categories=["Clothing, Shoes & Jewelry", "Men", "Shirts"],
                attributes={"material": {"cotton"}, "color": {"black", "white"}, "style": {"crewneck"}, "brand": {"hanes"}},
                price_val=15.00,
                store="Hanes",
                features="100% combed ringspun cotton",
            ),
            _make_record(
                parent_asin="B004",
                title="Outdoor Waterproof Hiking Boots",
                categories=["Clothing, Shoes & Jewelry", "Men", "Shoes"],
                attributes={"material": {"leather", "rubber"}, "color": {"brown"}, "style": {"hiking", "waterproof"}, "brand": {"columbia"}},
                price_val=120.00,
                store="Columbia",
                features="Waterproof leather construction with rugged rubber outsole",
            ),
            _make_record(
                parent_asin="B005",
                title="Vintage Denim Trucker Jacket",
                categories=["Clothing, Shoes & Jewelry", "Men", "Jackets"],
                attributes={"material": {"denim", "cotton"}, "color": {"blue"}, "style": {"vintage", "trucker"}, "brand": {"levi's"}},
                price_val=None,  # missing price
                store="Levi's",
                features="Classic denim jacket with button closure",
            ),
        ]
        self.index = CatalogIndex()
        self.index.build_from_records(self.records)

    def test_total_count(self) -> None:
        self.assertEqual(self.index.total_products, 5)

    def test_search_bm25(self) -> None:
        results = self.index.search_bm25("leather jacket", limit=5)
        self.assertTrue(len(results) >= 1)
        top_asin, top_score = results[0]
        self.assertEqual(top_asin, "B001")
        self.assertTrue(top_score > 0)

    def test_filter_by_category(self) -> None:
        jackets = self.index.filter_by_category("Jackets")
        self.assertEqual(jackets, frozenset({"B001", "B005"}))

        shoes = self.index.filter_by_category("Shoes")
        self.assertEqual(shoes, frozenset({"B002", "B004"}))

    def test_filter_by_attribute(self) -> None:
        leather_items = self.index.filter_by_attribute(Attribute.MATERIAL, "leather")
        self.assertEqual(leather_items, frozenset({"B001", "B004"}))

        black_items = self.index.filter_by_attribute(Attribute.COLOR, "black")
        self.assertEqual(black_items, frozenset({"B001", "B003"}))

        nike_items = self.index.filter_by_attribute(Attribute.BRAND, "nike")
        self.assertEqual(nike_items, frozenset({"B002"}))

    def test_filter_by_price_range(self) -> None:
        # Budget <= $100 (including missing price B005)
        under_100 = self.index.filter_by_price(max_price=100.00, include_unknown=True)
        self.assertEqual(under_100, frozenset({"B002", "B003", "B005"}))

        # Budget <= $100 (strictly excluding unknown)
        under_100_strict = self.index.filter_by_price(max_price=100.00, include_unknown=False)
        self.assertEqual(under_100_strict, frozenset({"B002", "B003"}))

        # Budget between $50 and $150
        mid_range = self.index.filter_by_price(min_price=50.00, max_price=150.00, include_unknown=False)
        self.assertEqual(mid_range, frozenset({"B002", "B004"}))

    def test_filter_by_exclusion(self) -> None:
        # Exclude black color
        not_black = self.index.filter_by_exclusion(Attribute.COLOR, "black")
        self.assertEqual(not_black, frozenset({"B002", "B004", "B005"}))

    def test_vocabulary_export(self) -> None:
        vocab = self.index.get_vocabulary_by_attribute()
        self.assertIn(Attribute.MATERIAL, vocab)
        self.assertIn("leather", vocab[Attribute.MATERIAL])
        self.assertIn("cotton", vocab[Attribute.MATERIAL])
        self.assertIn(Attribute.COLOR, vocab)
        self.assertIn("black", vocab[Attribute.COLOR])
        self.assertIn("blue", vocab[Attribute.COLOR])

    def test_term_pruning_and_idf(self) -> None:
        terms = ["vintage", "leather", "cowhide", "jacket", "the", "a"]
        pruned = self.index.prune_query_terms(terms, max_terms=3)
        self.assertEqual(len(pruned), 3)
        # Cowhide and leather should have high IDF since they are discriminative
        self.assertTrue(self.index.compute_idf("cowhide") > 0)

    def test_porter_stemmer_matching(self) -> None:
        # "jackets" should match product with "jacket", "running" should match "runner"
        results = self.index.search_bm25("jackets")
        asins = {asin for asin, score in results}
        self.assertIn("B001", asins)


if __name__ == "__main__":
    unittest.main()

