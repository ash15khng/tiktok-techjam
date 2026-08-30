from __future__ import annotations

import unittest

from devtools.development_splits import SplitConfig, assert_disjoint, build_splits


class DevelopmentSplitTest(unittest.TestCase):
    def setUp(self) -> None:
        scenarios = ("buying", "browsing", "intent_override", "boundary")
        self.samples = []
        self.products = {}
        for index in range(40):
            asin = f"B{index:09d}"
            self.samples.append({
                "sample_id": f"sample_{index:02d}",
                "scenario_type": scenarios[index % len(scenarios)],
                "ground_truth": {"parent_asin": asin},
            })
            self.products[asin] = {"title": f"Product family {index}"}

    def test_split_is_deterministic_complete_and_disjoint(self) -> None:
        config = SplitConfig(seed="fixed", holdout_fraction=0.20, development_folds=4)
        first = build_splits(self.samples, self.products, config)
        second = build_splits(self.samples, self.products, config)

        self.assertEqual(first, second)
        self.assertEqual(len(first.sealed_holdout), 8)
        self.assertEqual(sorted(len(value) for value in first.folds), [8, 8, 8, 8])
        assert_disjoint(first)

    def test_exact_title_family_never_crosses_a_partition(self) -> None:
        self.products["B000000000"]["title"] = "Shared Product"
        self.products["B000000001"]["title"] = " shared  product "
        splits = build_splits(
            self.samples,
            self.products,
            SplitConfig(seed="family", holdout_fraction=0.20, development_folds=4),
        )

        partitions = (splits.sealed_holdout, *splits.folds)
        locations = [
            index
            for index, partition in enumerate(partitions)
            if {"sample_00", "sample_01"} & set(partition)
        ]
        self.assertEqual(len(locations), 1)
        self.assertTrue({"sample_00", "sample_01"}.issubset(set(partitions[locations[0]])))


if __name__ == "__main__":
    unittest.main()
