"""Central catalog-derived schema for the fixed Agent API attributes.

API attribute names are fixed by competition contract. 
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from submission.src.catalog.models import ProductRecord
from submission.src.catalog.normalization import normalize_text, tokenize


@dataclass(frozen=True)
class AttributeSpec:
    name: str
    detail_key_fragments: tuple[str, ...]
    question: str


ATTRIBUTE_SPECS = (
    AttributeSpec(
        "feature",
        ("special feature", "special features", "product benefits"),
        "Which feature matters most for the product you want?",
    ),
    AttributeSpec(
        "material",
        ("material", "fabric", "metal type"),
        "What material would you like it to be made of?",
    ),
    AttributeSpec("color", ("color", "colour"), "What color would you like it to be in?"),
    AttributeSpec(
        "style",
        (
            "style",
            "pattern",
            "fit type",
            "neck style",
            "sleeve type",
            "closure type",
            "shape",
            "theme",
            "finish type",
            "collar style",
            "shirt form type",
            "top style",
        ),
        "What style or fit do you prefer?",
    ),
    AttributeSpec("size", ("size",), "What size or fit requirement should I use?"),
    AttributeSpec(
        "use_case",
        ("sport", "occasion", "recommended uses", "specific uses", "lifestyle"),
        "What occasion or use case is this for?",
    ),
    AttributeSpec("budget", (), "What does your budget range look like?"),
    AttributeSpec("brand", ("brand", "brand name"), "Do you prefer any specific brands?"),
    AttributeSpec("category", (), "Which product category are you interested in?"),
)

ATTRIBUTE_ORDER = tuple(spec.name for spec in ATTRIBUTE_SPECS)
VALUE_RESOLUTION_ORDER = (
    "material", "color", "size", "use_case", "style", "brand", "category", "feature",
) # what will likely cut the search space most (when answer isn't null).
QUESTION_TEXT = {spec.name: spec.question for spec in ATTRIBUTE_SPECS} | {
    "other": "What other requirement matters most for the item you want?"
}

_SPEC_BY_NAME = {spec.name: spec for spec in ATTRIBUTE_SPECS}
_VALUE_SPLIT_RE = re.compile(r"\s*(?:[,;/|]|\s+-\s+)\s*")
_BUDGET_CUE_RE = re.compile(
    r"(?:\$\s*\d|\b(?:budget|price|cost|under|below|over|above|between|"
    r"up\s+to|at\s+(?:most|least))\s+\$?\d)",
    re.IGNORECASE,
)
_CUE_PATTERNS = (
    ("material", re.compile(r"\b(?:material|fabric|composition|made\s+(?:of|from))\b", re.I)),
    ("color", re.compile(r"\b(?:color|colour|shade)\b", re.I)),
    ("size", re.compile(r"\b(?:size|sizing|width|wide|narrow)\b", re.I)),
    (
        "style",
        re.compile(
            r"\b(?:style|fit|pattern|heel|toe|neck|sleeve|closure|silhouette)\b",
            re.I,
        ),
    ),
    ("brand", re.compile(r"\b(?:brand|manufacturer|made\s+by)\b", re.I)),
    ("use_case", re.compile(r"\b(?:occasion|use\s*case|activity|sport|lifestyle)\b", re.I)),
    ("feature", re.compile(r"\b(?:feature|function|benefit)\b", re.I)),
    ("category", re.compile(r"\b(?:category|product\s+type|kind\s+of\s+item)\b", re.I)),
)
_SIZE_KEY_EXCLUSIONS = frozenset(
    {"package", "dimension", "dimensions", "screen", "file", "assembled", "weight", "map"}
)
_INFERABLE_ATTRIBUTES = frozenset(("material", "color", "size", "style", "use_case"))
_VALUE_NOISE = frozenset(
    {"", "n/a", "na", "none", "no", "unknown", "other", "default", "not applicable", "one", "type"}
)

# Catalog-linking bounds prevent accidental phrases and one-off metadata noise
# from becoming universal attribute values. Increasing the phrase limits raises
# recall and index/startup cost; lowering them favors precision. Prefix pruning
# at these values matched the reference scan on 2,000 products with zero diffs.
FEATURE_SAMPLE_LIMIT = 3
MIN_FEATURE_TERM_CHARS = 4
MIN_REPEAT_SUPPORT = 2
MIN_INFERRED_TERM_CHARS = 3
MAX_ATTRIBUTE_VALUE_TERMS = 6
MAX_ATTRIBUTE_VALUE_CHARS = 100
ATTRIBUTE_VALUE_CACHE_SIZE = 8_192
INFERRED_VALUE_CACHE_SIZE = 4_096

# More quantiles create finer budget groups but reduce candidates per partition;
# fewer quantiles blur the catalog's skewed price distribution. These log-space
# boundaries replaced fixed $25 buckets after inspecting the 50k catalog.
PRICE_QUANTILES = (0.10, 0.25, 0.50, 0.75, 0.90)
PRICE_BOUNDARY_RELATIVE_TOLERANCE = 1e-12

# Raising the floor asks sparse-but-natural fields more often; lowering it trusts
# missing metadata too literally. Raising evidence weight follows catalog
# coverage more strongly. The current blend is the retained catalog-derived
# baseline; per-session replies update it separately in dialog state.
ANSWERABILITY_FLOOR = 0.35
ANSWERABILITY_CEILING = 0.95
ANSWERABILITY_EVIDENCE_WEIGHT = 0.60
NEUTRAL_ANSWERABILITY = 0.50


class AttributeValueResolver(Protocol):
    def candidate_attributes(self, text: str, *, preferred: str | None = None) -> tuple[str, ...]:
        """Return catalog-supported attributes for a value phrase."""

    def matched_values(self, text: str) -> tuple[tuple[str, str], ...]:
        """Return longest catalog-supported ``(attribute, value)`` matches."""


class EmptyAttributeResolver:
    def candidate_attributes(self, text: str, *, preferred: str | None = None) -> tuple[str, ...]:
        return ()

    def matched_values(self, text: str) -> tuple[tuple[str, str], ...]:
        return ()


def cue_attributes(text: str) -> tuple[str, ...]:
    """Recognize API-level attribute language, not catalog value lists."""

    result: list[str] = []
    if _BUDGET_CUE_RE.search(text):
        result.append("budget")
    for attribute, pattern in _CUE_PATTERNS:
        if pattern.search(text) and attribute not in result:
            result.append(attribute)
    return tuple(result)


class CatalogAttributeRegistry:
    """Derive value lexicons and product evidence from catalog metadata."""

    def __init__(self, products: dict[str, ProductRecord]) -> None:
        self.products = products
        self._direct: dict[str, dict[str, tuple[str, ...]]] = {}
        value_counts: dict[str, Counter[str]] = {name: Counter() for name in ATTRIBUTE_ORDER}
        value_document_counts: dict[str, Counter[str]] = {
            name: Counter() for name in ATTRIBUTE_ORDER
        }
        coverage_counts: Counter[str] = Counter()
        prices: list[float] = []

        for parent_asin, product in products.items():
            values = self._direct_values(product)
            self._direct[parent_asin] = values
            coverage_counts.update(attribute for attribute, items in values.items() if items)
            if product.features:
                coverage_counts["feature"] += 1
            for attribute, attribute_values in values.items():
                seen: set[str] = set()
                for value in attribute_values:
                    for variant in _value_variants(attribute, value):
                        value_counts[attribute][variant] += 1
                        seen.add(variant)
                value_document_counts[attribute].update(seen)
            feature_terms = {
                term
                for term in tokenize(" ".join(product.features[:FEATURE_SAMPLE_LIMIT]))
                if len(term) >= MIN_FEATURE_TERM_CHARS and term not in _VALUE_NOISE
            }
            value_counts["feature"].update(feature_terms)
            value_document_counts["feature"].update(feature_terms)
            if product.price is not None and product.price > 0 and math.isfinite(product.price):
                prices.append(product.price)
                coverage_counts["budget"] += 1

        self.value_counts = value_counts
        self.value_document_counts = value_document_counts
        self._phrase_attributes: dict[str, Counter[str]] = defaultdict(Counter)
        for attribute, counts in value_document_counts.items():
            if attribute == "budget":
                continue
            for phrase, count in counts.items():
                terms = tokenize(phrase, drop_stopwords=False)
                if not _usable_value(phrase, terms) or (
                    len(terms) == 1
                    and count < MIN_REPEAT_SUPPORT
                    and attribute in {"brand", "feature", "style"}
                ):
                    continue
                self._phrase_attributes[phrase][attribute] += count
                if attribute not in {"brand", "category"}:
                    for term in terms:
                        if (
                            len(term) >= MIN_INFERRED_TERM_CHARS
                            and counts[term] >= MIN_REPEAT_SUPPORT
                            and term not in _VALUE_NOISE
                        ):
                            self._phrase_attributes[term][attribute] += counts[term]
        self._max_value_terms = min(
            MAX_ATTRIBUTE_VALUE_TERMS,
            max(
                (
                    len(tokenize(value, drop_stopwords=False))
                    for value in self._phrase_attributes
                ),
                default=1,
            ),
        )
        self._inference_prefixes: set[tuple[str, ...]] = set()
        for phrase, attributes in self._phrase_attributes.items():
            if not any(attribute in _INFERABLE_ATTRIBUTES for attribute in attributes):
                continue
            phrase_terms = tokenize(phrase, drop_stopwords=False)
            self._inference_prefixes.update(
                phrase_terms[:width] for width in range(1, len(phrase_terms) + 1)
            )
        self.price_boundaries = _log_quantile_boundaries(prices)
        self._baseline_answerability = {
            attribute: _answerability_prior(
                coverage_counts[attribute] / max(1, len(products)),
                value_document_counts[attribute],
            )
            for attribute in ATTRIBUTE_ORDER
        }

    def candidate_attributes(self, text: str, *, preferred: str | None = None) -> tuple[str, ...]:
        normalized = normalize_text(text).strip(" -;,./\\")
        terms = tokenize(normalized, drop_stopwords=False)
        if not terms:
            return ()
        scores: Counter[str] = Counter()
        matched_lengths: dict[str, int] = defaultdict(int)
        maximum = min(len(terms), self._max_value_terms)
        for width in range(maximum, 0, -1):
            for index in range(len(terms) - width + 1):
                phrase = " ".join(terms[index : index + width])
                for attribute, support in self._phrase_attributes.get(phrase, {}).items():
                    scores[attribute] += support * width * width
                    matched_lengths[attribute] = max(matched_lengths[attribute], width)
        if not scores:
            return ()
        ordered = sorted(
            scores,
            key=lambda attribute: (
                attribute != preferred,
                -matched_lengths[attribute],
                attribute == "feature",
                -scores[attribute],
                VALUE_RESOLUTION_ORDER.index(attribute),
            ),
        )
        return tuple(ordered)

    def matched_values(self, text: str) -> tuple[tuple[str, str], ...]:
        """Link explicit words to catalog-derived values without a hand-built lexicon.

        The state reducer uses this during targeted corrections, such as
        replacing ``red`` in ``red shoes`` without splitting arbitrary product
        phrases. Longest non-overlapping catalog values win; stable attribute
        ordering resolves ambiguous metadata.
        """

        terms = tokenize(normalize_text(text), drop_stopwords=False)
        matches: list[tuple[int, int, str, str]] = []
        maximum = min(len(terms), self._max_value_terms)
        for width in range(maximum, 0, -1):
            for index in range(len(terms) - width + 1):
                phrase = " ".join(terms[index : index + width])
                attributes = self._phrase_attributes.get(phrase)
                if not attributes:
                    continue
                ordered = sorted(
                    attributes,
                    key=lambda attribute: (
                        attribute == "feature",
                        -attributes[attribute],
                        VALUE_RESOLUTION_ORDER.index(attribute),
                    ),
                )
                matches.append((index, width, ordered[0], phrase))

        selected: list[tuple[str, str]] = []
        occupied: set[int] = set()
        for index, width, attribute, phrase in sorted(
            matches,
            key=lambda item: (-item[1], item[0], VALUE_RESOLUTION_ORDER.index(item[2])),
        ):
            positions = set(range(index, index + width))
            if positions & occupied:
                continue
            occupied.update(positions)
            selected.append((attribute, phrase))
        return tuple(selected)

    @lru_cache(maxsize=ATTRIBUTE_VALUE_CACHE_SIZE)
    def values_for_product(self, parent_asin: str, attribute: str) -> tuple[str, ...]:
        product = self.products[parent_asin]
        direct = list(self._direct.get(parent_asin, {}).get(attribute, ()))
        if attribute == "feature":
            direct.extend(product.features[:FEATURE_SAMPLE_LIMIT])
        if attribute == "budget":
            bucket = self.budget_bucket(product.price)
            return (bucket,) if bucket else ()
        if attribute not in {"material", "color", "size", "style", "use_case"}:
            return tuple(dict.fromkeys(value for value in direct if value))
        inferred = dict(self._inferred_values_for_product(parent_asin)).get(attribute, ())
        return tuple(dict.fromkeys((*direct, *inferred)))

    @lru_cache(maxsize=INFERRED_VALUE_CACHE_SIZE)
    def _inferred_values_for_product(
        self,
        parent_asin: str,
    ) -> tuple[tuple[str, tuple[str, ...]], ...]:
        text_terms = tokenize(self.products[parent_asin].search_text, drop_stopwords=False)
        matches: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
        for start in range(len(text_terms)):
            maximum_end = min(len(text_terms), start + self._max_value_terms)
            for end in range(start + 1, maximum_end + 1):
                phrase_terms = text_terms[start:end]
                if phrase_terms not in self._inference_prefixes:
                    break
                phrase = " ".join(phrase_terms)
                for attribute in self._phrase_attributes.get(phrase, ()):
                    if attribute in _INFERABLE_ATTRIBUTES:
                        matches[attribute].append((len(phrase_terms), start, phrase))
        return tuple(
            (
                attribute,
                tuple(
                    dict.fromkeys(
                        phrase
                        for _, _, phrase in sorted(values, key=lambda item: (-item[0], item[1]))
                    )
                ),
            )
            for attribute, values in matches.items()
        )

    def representative_value(self, parent_asin: str, attribute: str) -> str | None:
        values = self.values_for_product(parent_asin, attribute)
        if not values:
            return None
        return values[-1] if attribute == "category" else values[0]

    def baseline_answerability(self, attribute: str) -> float:
        """Return an O(1), catalog-derived prior for clarification usefulness."""

        return self._baseline_answerability.get(attribute, NEUTRAL_ANSWERABILITY)

    def budget_bucket(self, price: float | None) -> str | None:
        if price is None or price <= 0 or not math.isfinite(price):
            return None
        for index, boundary in enumerate(self.price_boundaries):
            if price <= boundary * (1.0 + PRICE_BOUNDARY_RELATIVE_TOLERANCE):
                return f"q{index}"
        return f"q{len(self.price_boundaries)}"

    @staticmethod
    def question_text(attribute: str) -> str | None:
        return QUESTION_TEXT.get(attribute)

    @staticmethod
    def question_attributes() -> tuple[str, ...]:
        return ATTRIBUTE_ORDER

    @staticmethod
    def _direct_values(product: ProductRecord) -> dict[str, tuple[str, ...]]:
        values: dict[str, list[str]] = defaultdict(list)
        values["category"].extend(product.categories)
        if product.store:
            values["brand"].append(product.store)
        for raw_key, raw_value in product.detail_pairs:
            for attribute in _attributes_for_detail_key(raw_key):
                values[attribute].extend(_split_value(raw_value))
        return {
            attribute: tuple(dict.fromkeys(value for value in attribute_values if value))
            for attribute, attribute_values in values.items()
        }


def _attributes_for_detail_key(raw_key: str) -> tuple[str, ...]:
    key = normalize_text(raw_key)
    key_terms = set(tokenize(key, drop_stopwords=False))
    result: list[str] = []
    for spec in ATTRIBUTE_SPECS:
        if not spec.detail_key_fragments:
            continue
        if spec.name == "size" and key_terms & _SIZE_KEY_EXCLUSIONS:
            continue
        if any(fragment in key for fragment in spec.detail_key_fragments):
            result.append(spec.name)
    return tuple(result)


def _split_value(raw_value: str) -> tuple[str, ...]:
    normalized = normalize_text(raw_value)
    if normalized in _VALUE_NOISE:
        return ()
    parts = tuple(
        part
        for part in _VALUE_SPLIT_RE.split(normalized)
        if part and part not in _VALUE_NOISE
    )
    return parts or ((normalized,) if normalized else ())


def _value_variants(attribute: str, value: str) -> tuple[str, ...]:
    normalized = normalize_text(value)
    terms = tokenize(normalized, drop_stopwords=False)
    variants = [normalized]
    if len(terms) == 1:
        variants.append(terms[0])
    elif len(terms) < MAX_ATTRIBUTE_VALUE_TERMS and attribute not in {"brand", "category"}:
        variants.extend(term for term in terms if len(term) >= MIN_INFERRED_TERM_CHARS)
    return tuple(dict.fromkeys(variant for variant in variants if variant))


def _usable_value(phrase: str, terms: tuple[str, ...]) -> bool:
    return (
        bool(terms)
        and phrase not in _VALUE_NOISE
        and len(phrase) <= MAX_ATTRIBUTE_VALUE_CHARS
        and len(terms) <= MAX_ATTRIBUTE_VALUE_TERMS
        and not all(term.isdigit() for term in terms)
    )


def _log_quantile_boundaries(prices: list[float]) -> tuple[float, ...]:
    if not prices:
        return ()
    logs = sorted(math.log(value) for value in prices if value > 0)
    boundaries: list[float] = []
    for fraction in PRICE_QUANTILES:
        index = min(len(logs) - 1, round((len(logs) - 1) * fraction))
        value = math.exp(logs[index])
        if not boundaries or value > boundaries[-1]:
            boundaries.append(value)
    return tuple(boundaries)


def _answerability_prior(coverage: float, counts: Counter[str]) -> float:
    """Blend metadata coverage with repeated-value support.

    The neutral floor prevents sparse structured metadata from claiming that a
    customer cannot answer an ordinary question. Candidate-level coverage still
    controls whether asking that question can partition the current result set.
    """

    total_mentions = sum(counts.values())
    repeated_mentions = sum(count for count in counts.values() if count >= MIN_REPEAT_SUPPORT)
    repeat_support = repeated_mentions / total_mentions if total_mentions else coverage
    evidence = math.sqrt(max(0.0, coverage * repeat_support))
    return min(
        ANSWERABILITY_CEILING,
        max(
            ANSWERABILITY_FLOOR,
            ANSWERABILITY_FLOOR + ANSWERABILITY_EVIDENCE_WEIGHT * evidence,
        ),
    )
