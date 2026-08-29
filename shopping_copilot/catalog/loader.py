from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator, Mapping

from shopping_copilot.catalog.extraction import CatalogAttributeExtractor, normalize_str
from shopping_copilot.catalog.models import ProductRecord
from shopping_copilot.catalog.price import parse_price


def _clean_text_field(val: Any) -> str:
    """Converts a raw JSON field value into a normalized single search text string."""
    if val is None:
        return ""
    if isinstance(val, str):
        return normalize_str(val)
    if isinstance(val, (list, tuple)):
        return " ".join(normalize_str(str(item)) for item in val if item is not None)
    if isinstance(val, dict):
        return " ".join(
            f"{normalize_str(str(k))} {normalize_str(str(v))}"
            for k, v in val.items()
            if v is not None
        )
    return normalize_str(str(val))


class CatalogLoader:
    """Streams, validates, and transforms raw catalog JSONL records into ProductRecord instances."""

    def __init__(self, extractor: CatalogAttributeExtractor | None = None) -> None:
        self.extractor = extractor or CatalogAttributeExtractor()

    def parse_record(self, raw: Mapping[str, Any]) -> ProductRecord:
        """Parses and validates a single raw catalog product dictionary."""
        raw_asin = raw.get("parent_asin")
        if not raw_asin or not isinstance(raw_asin, str) or not raw_asin.strip():
            raise ValueError(f"Record missing valid 'parent_asin': {raw}")

        parent_asin = raw_asin.strip()

        # Build search fields
        title = _clean_text_field(raw.get("title"))
        features = _clean_text_field(raw.get("features"))
        description = _clean_text_field(raw.get("description"))
        details = _clean_text_field(raw.get("details"))
        store = _clean_text_field(raw.get("store"))

        # Parse categories
        raw_cats = raw.get("categories")
        categories: list[str] = []
        if isinstance(raw_cats, (list, tuple)):
            for c in raw_cats:
                c_norm = normalize_str(str(c))
                if c_norm:
                    categories.append(c_norm)
        elif isinstance(raw_cats, str):
            c_norm = normalize_str(raw_cats)
            if c_norm:
                categories.append(c_norm)
        cat_tuple = tuple(categories)
        categories_text = " ".join(categories)

        search_fields: dict[str, str] = {
            "title": title,
            "features": features,
            "description": description,
            "details": details,
            "store": store,
            "categories": categories_text,
        }

        # Track field presence
        present_fields = {k for k, v in search_fields.items() if bool(v)}

        # Extract attributes & evidence
        attributes, evidence = self.extractor.extract(raw, search_fields)

        # Parse price
        price = parse_price(raw.get("price"))

        # Ratings
        avg_rating: float | None = None
        raw_rating = raw.get("average_rating")
        if raw_rating is not None:
            try:
                avg_rating = round(float(raw_rating), 2)
            except (ValueError, TypeError):
                avg_rating = None

        rating_num: int | None = None
        raw_num = raw.get("rating_number")
        if raw_num is not None:
            try:
                rating_num = int(raw_num)
            except (ValueError, TypeError):
                rating_num = None

        return ProductRecord(
            parent_asin=parent_asin,
            raw=raw,
            search_fields=search_fields,
            categories=cat_tuple,
            attributes=attributes,
            attribute_evidence=evidence,
            price=price,
            average_rating=avg_rating,
            rating_number=rating_num,
            field_presence=frozenset(present_fields),
        )

    def stream_file(self, file_path: str | Path) -> Iterator[ProductRecord]:
        """Streams product records line-by-line from a JSONL file, validating uniqueness."""
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Catalog file not found: {path}")

        seen_asins: set[str] = set()
        with path.open("r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as err:
                    raise ValueError(f"Malformed JSON on line {line_no} of {path}: {err}") from err

                record = self.parse_record(data)
                if record.parent_asin in seen_asins:
                    raise ValueError(f"Duplicate parent_asin detected: '{record.parent_asin}' at line {line_no}")
                seen_asins.add(record.parent_asin)
                yield record

    def load_all(self, file_path: str | Path) -> list[ProductRecord]:
        """Loads and returns all records from the catalog file."""
        return list(self.stream_file(file_path))

