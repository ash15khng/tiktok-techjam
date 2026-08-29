from __future__ import annotations

import unittest
from shopping_copilot.catalog.models import PriceValue, ProductRecord
from shopping_copilot.catalog.price import parse_price
from shopping_copilot.catalog.extraction import CatalogAttributeExtractor
from shopping_copilot.catalog.loader import CatalogLoader
from shopping_copilot.understanding.models import Attribute


class TestPriceParser(unittest.TestCase):
    def test_parse_numeric_and_exact(self) -> None:
        p1 = parse_price(29.99)
        self.assertEqual(p1.kind, "exact")
        self.assertEqual(p1.lower, 29.99)
        self.assertEqual(p1.upper, 29.99)
        self.assertTrue(p1.matches_budget(budget_max=30.0))
        self.assertFalse(p1.matches_budget(budget_max=20.0))

        p2 = parse_price("$45.50")
        self.assertEqual(p2.kind, "exact")
        self.assertEqual(p2.lower, 45.50)

    def test_parse_range(self) -> None:
        p1 = parse_price("$15.00 - $35.00")
        self.assertEqual(p1.kind, "range")
        self.assertEqual(p1.lower, 15.00)
        self.assertEqual(p1.upper, 35.00)
        self.assertTrue(p1.matches_budget(budget_max=20.0))
        self.assertFalse(p1.matches_budget(budget_max=10.0))

        p2 = parse_price("from $10 to $20")
        self.assertEqual(p2.kind, "range")
        self.assertEqual(p2.lower, 10.00)
        self.assertEqual(p2.upper, 20.00)

    def test_parse_lower_bound(self) -> None:
        p1 = parse_price("From $12.99")
        self.assertEqual(p1.kind, "lower_bound")
        self.assertEqual(p1.lower, 12.99)
        self.assertIsNone(p1.upper)
        self.assertTrue(p1.matches_budget(budget_max=15.0))
        self.assertFalse(p1.matches_budget(budget_max=10.0))

        p2 = parse_price("$25+")
        self.assertEqual(p2.kind, "lower_bound")
        self.assertEqual(p2.lower, 25.0)

    def test_parse_unknown_and_invalid(self) -> None:
        p1 = parse_price(None)
        self.assertEqual(p1.kind, "unknown")
        self.assertIsNone(p1.lower)
        self.assertTrue(p1.matches_budget(budget_max=5.0))  # missing price doesn't contradict

        p2 = parse_price("N/A")
        self.assertEqual(p2.kind, "unknown")


class TestCatalogExtraction(unittest.TestCase):
    def setUp(self) -> None:
        self.extractor = CatalogAttributeExtractor()

    def test_extract_structured_details(self) -> None:
        raw = {
            "parent_asin": "B00TEST123",
            "title": "Basic Athletic Tee",
            "store": "Nike",
            "details": {
                "Fabric Type": "100% Cotton",
                "Fit Type": "Slim Fit",
                "Color": "Navy Blue, White",
            },
        }
        search_fields = {
            "title": "basic athletic tee",
            "features": "lightweight and breathable",
            "description": "",
            "store": "nike",
            "categories": "clothing men shirts",
        }
        attributes, evidence = self.extractor.extract(raw, search_fields)

        self.assertIn("material", attributes)
        self.assertIn("cotton", attributes["material"])
        self.assertIn("style", attributes)
        self.assertIn("slim fit", attributes["style"])
        self.assertIn("brand", attributes)
        self.assertIn("nike", attributes["brand"])
        self.assertIn("color", attributes)

        # Check evidence provenance
        mat_evidence = evidence["material"]
        self.assertTrue(any(e.source_field == "details.Fabric Type" for e in mat_evidence))

    def test_extract_unstructured_text(self) -> None:
        raw = {
            "parent_asin": "B00TEST456",
            "title": "Men's Waterproof Wool Winter Jacket in Olive",
            "features": ["100% genuine leather trim", "thermal insulated fleece lining"],
        }
        search_fields = {
            "title": "men's waterproof wool winter jacket in olive",
            "features": "100% genuine leather trim thermal insulated fleece lining",
            "description": "",
            "store": "",
            "categories": "jackets & coats",
        }
        attributes, evidence = self.extractor.extract(raw, search_fields)

        self.assertIn("wool", attributes["material"])
        self.assertIn("fleece", attributes["material"])
        self.assertIn("leather", attributes["material"])
        self.assertIn("olive", attributes["color"])
        self.assertIn("waterproof", attributes["style"])
        self.assertIn("men", attributes["style"])


class TestCatalogLoader(unittest.TestCase):
    def setUp(self) -> None:
        self.loader = CatalogLoader()

    def test_parse_valid_record(self) -> None:
        raw = {
            "parent_asin": "B01XYZ890",
            "title": "Women's Running Shoes",
            "price": "$59.99",
            "average_rating": 4.5,
            "rating_number": 120,
            "categories": ["Clothing, Shoes & Jewelry", "Women", "Shoes"],
            "features": ["Breathable mesh upper", "Rubber sole"],
            "store": "Adidas",
        }
        record = self.loader.parse_record(raw)
        self.assertEqual(record.parent_asin, "B01XYZ890")
        self.assertEqual(record.price.kind, "exact")
        self.assertEqual(record.price.lower, 59.99)
        self.assertEqual(record.average_rating, 4.5)
        self.assertEqual(record.rating_number, 120)
        self.assertIn("adidas", record.attributes["brand"])

    def test_missing_asin_raises_error(self) -> None:
        raw = {"title": "No ASIN item"}
        with self.assertRaises(ValueError):
            self.loader.parse_record(raw)


if __name__ == "__main__":
    unittest.main()
