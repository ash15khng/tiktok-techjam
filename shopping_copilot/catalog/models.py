from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping


@dataclass(frozen=True)
class PriceValue:
    """Represents a structured price for a catalog product.
    
    Attributes:
        lower: Lower bound price or exact price if lower == upper.
        upper: Upper bound price or exact price if lower == upper.
        kind: Classification of the price representation:
              - 'exact': single fixed price (lower == upper).
              - 'range': price interval (lower < upper).
              - 'lower_bound': minimum starting price (e.g. "From $10").
              - 'unknown': unparseable or absent price.
    """
    lower: float | None
    upper: float | None
    kind: Literal["exact", "range", "lower_bound", "unknown"]

    def matches_budget(self, budget_max: float | None = None, budget_min: float | None = None) -> bool:
        """Checks if product price satisfies the given budget constraints."""
        if self.kind == "unknown":
            # Missing price is unknown; does not contradict
            return True
        if budget_max is not None and self.lower is not None:
            if self.lower > budget_max:
                return False
        if budget_min is not None and self.upper is not None:
            if self.upper < budget_min:
                return False
        return True


@dataclass(frozen=True)
class AttributeEvidence:
    """Provenance record for an extracted attribute value."""
    value: str
    source_field: str
    extraction: Literal["structured", "exact_alias", "text_rule"]
    confidence: float


@dataclass(frozen=True)
class ProductRecord:
    """Canonical immutable product record within the catalog."""
    parent_asin: str
    raw: Mapping[str, object]
    search_fields: Mapping[str, str]
    categories: tuple[str, ...]
    attributes: Mapping[str, frozenset[str]]
    attribute_evidence: Mapping[str, tuple[AttributeEvidence, ...]]
    price: PriceValue
    average_rating: float | None
    rating_number: int | None
    field_presence: frozenset[str]
