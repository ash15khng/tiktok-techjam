from __future__ import annotations

import unittest

from shopping_copilot.catalog.normalization import tokenize


class NormalizationTest(unittest.TestCase):
    def test_single_digit_sizes_remain_searchable(self) -> None:
        self.assertEqual(tokenize("size 7"), ("size", "7"))

    def test_single_letter_noise_is_still_removed(self) -> None:
        self.assertEqual(tokenize("a red shoe"), ("red", "shoe"))


if __name__ == "__main__":
    unittest.main()
