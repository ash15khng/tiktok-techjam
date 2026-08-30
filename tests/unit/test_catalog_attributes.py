from __future__ import annotations

import unittest

from shopping_copilot.catalog.attributes import CatalogAttributeRegistry
from shopping_copilot.catalog.models import ProductRecord
from shopping_copilot.understanding.interpreter import MessageInterpreter
from shopping_copilot.understanding.models import Attribute


def product(
    parent_asin: str,
    *,
    title: str,
    details: tuple[tuple[str, str], ...],
    store: str,
    price: float | None,
) -> ProductRecord:
    return ProductRecord(
        parent_asin=parent_asin,
        title=title,
        categories=("Footwear", "Trail Shoes"),
        features=("Storm shield construction",),
        details=tuple(f"{key} {value}" for key, value in details),
        store=store,
        description=(),
        price=price,
        average_rating=4.0,
        rating_number=10,
        detail_pairs=details,
    )


class CatalogAttributeRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.products = {
            "A": product(
                "A",
                title="Cerulean linen trail shoe",
                details=(
                    ("Color", "Cerulean"),
                    ("Fabric Type", "Linen"),
                    ("Occasion", "Monsoon Trek"),
                    ("Style", "Avant Garde"),
                    ("Size", "42 Long"),
                    ("Package Dimensions", "10 x 5 x 2 inches"),
                ),
                store="North Star",
                price=19.0,
            ),
            "B": product(
                "B",
                title="Saffron linen walking shoe",
                details=(
                    ("Colour", "Saffron"),
                    ("Material", "Linen"),
                    ("Recommended Uses for Product", "City Walking"),
                    ("Fit Type", "Relaxed"),
                ),
                store="South Star",
                price=119.0,
            ),
            "C": product(
                "C",
                title="Cerulean linen commuter shoe",
                details=(),
                store="",
                price=None,
            ),
        }
        self.registry = CatalogAttributeRegistry(self.products)

    def test_catalog_values_resolve_without_value_word_lists(self) -> None:
        self.assertEqual(self.registry.candidate_attributes("cerulean")[0], "color")
        self.assertEqual(self.registry.candidate_attributes("linen")[0], "material")
        self.assertEqual(self.registry.candidate_attributes("monsoon trek")[0], "use_case")
        self.assertEqual(self.registry.candidate_attributes("north star")[0], "brand")
        self.assertEqual(self.registry.candidate_attributes("trail shoes")[0], "category")

    def test_physical_package_dimensions_do_not_become_wearable_size(self) -> None:
        size_values = self.registry.values_for_product("A", "size")

        self.assertIn("42 long", size_values)
        self.assertNotIn("10 x 5 x 2 inches", size_values)

    def test_catalog_values_are_inferred_from_unstructured_product_text(self) -> None:
        self.assertIn("cerulean", self.registry.values_for_product("C", "color"))
        self.assertIn("linen", self.registry.values_for_product("C", "material"))

    def test_interpreter_covers_contract_attributes_with_catalog_native_values(self) -> None:
        interpreter = MessageInterpreter(attribute_resolver=self.registry)
        cases = {
            "I'm looking for trail shoes.": Attribute.CATEGORY,
            "Linen is non-negotiable.": Attribute.MATERIAL,
            "Cerulean, please.": Attribute.COLOR,
            "42 Long": Attribute.SIZE,
            "Avant Garde": Attribute.STYLE,
            "North Star": Attribute.BRAND,
            "under $80": Attribute.BUDGET,
            "The feature I care about is storm shielding.": Attribute.FEATURE,
            "Monsoon Trek": Attribute.USE_CASE,
        }
        for message, expected in cases.items():
            with self.subTest(message=message):
                frame = interpreter.parse_deterministic(message, last_ask_attribute=None)
                self.assertEqual(frame.slot_updates[0].attribute, expected)

    def test_budget_partitions_are_monotonic_and_missing_neutral(self) -> None:
        self.assertIsNone(self.registry.budget_bucket(None))
        self.assertLess(
            int(self.registry.budget_bucket(19.0).lstrip("q")),
            int(self.registry.budget_bucket(119.0).lstrip("q")),
        )

    def test_answerability_priors_are_catalog_derived_and_bounded(self) -> None:
        for attribute in self.registry.question_attributes():
            prior = self.registry.baseline_answerability(attribute)
            self.assertGreaterEqual(prior, 0.35)
            self.assertLessEqual(prior, 0.95)

        self.assertGreater(
            self.registry.baseline_answerability("category"),
            self.registry.baseline_answerability("size"),
        )


if __name__ == "__main__":
    unittest.main()
