from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from typing import Any, Mapping

from shopping_copilot.catalog.models import AttributeEvidence
from shopping_copilot.understanding.models import Attribute

# Alias mapping from raw detail keys to standard Attribute
STRUCTURED_KEY_MAPPING: dict[str, Attribute] = {
    # Material
    "material": Attribute.MATERIAL,
    "fabric type": Attribute.MATERIAL,
    "fabric": Attribute.MATERIAL,
    "material composition": Attribute.MATERIAL,
    "outer material": Attribute.MATERIAL,
    "composition": Attribute.MATERIAL,
    "care instructions": Attribute.MATERIAL,
    # Color
    "color": Attribute.COLOR,
    "colour": Attribute.COLOR,
    "color name": Attribute.COLOR,
    "shade": Attribute.COLOR,
    # Size
    "size": Attribute.SIZE,
    "item size": Attribute.SIZE,
    "shoe size": Attribute.SIZE,
    "dimensions": Attribute.SIZE,
    # Style / Fit
    "style": Attribute.STYLE,
    "fit type": Attribute.STYLE,
    "closure type": Attribute.STYLE,
    "sleeve type": Attribute.STYLE,
    "neck style": Attribute.STYLE,
    "pattern": Attribute.STYLE,
    "collar style": Attribute.STYLE,
    "rise style": Attribute.STYLE,
    "leg style": Attribute.STYLE,
    # Brand
    "brand": Attribute.BRAND,
    "manufacturer": Attribute.BRAND,
    # Use Case / Occasion
    "occasion": Attribute.USE_CASE,
    "use case": Attribute.USE_CASE,
    "activity": Attribute.USE_CASE,
    "target audience": Attribute.STYLE,
    "department": Attribute.STYLE,
}

# High-precision keyword lexicons for unstructured text scanning
MATERIAL_LEXICON = {
    "cotton", "polyester", "wool", "silk", "linen", "leather", "genuine leather",
    "fleece", "denim", "canvas", "spandex", "nylon", "cashmere", "rayon", "viscose",
    "suede", "velvet", "satin", "chiffon", "flannel", "bamboo", "acrylic", "modal",
    "elastane", "microfiber", "tweed", "corduroy", "sherpa", "mesh", "foam",
}

COLOR_LEXICON = {
    "black", "white", "blue", "navy", "navy blue", "red", "green", "olive", "grey",
    "gray", "brown", "beige", "tan", "khaki", "yellow", "orange", "pink", "purple",
    "violet", "burgundy", "maroon", "gold", "silver", "teal", "turquoise", "coral",
    "charcoal", "cream", "ivory", "bronze", "copper", "rose gold", "multicolor",
    "multi-color", "rainbow",
}

GENDER_LEXICON = {
    "men", "mens", "men's", "women", "womens", "women's", "boys", "boy's", "girls",
    "girl's", "unisex", "baby", "toddler", "kids", "children",
}

STYLE_LEXICON = {
    "slim fit", "regular fit", "loose fit", "relaxed fit", "classic fit", "skinny",
    "oversized", "crew neck", "v-neck", "hooded", "sleeveless", "short sleeve",
    "long sleeve", "zipper", "button down", "pull on", "ankle length", "high rise",
    "mid rise", "low rise", "waterproof", "water resistant", "breathable", "lightweight",
    "heavyweight", "insulated", "windproof", "elastic", "adjustable", "thermal",
}


def normalize_str(text: str) -> str:
    """Applies Unicode NFKC normalization, casefolding, and whitespace collapse."""
    if not text:
        return ""
    norm = unicodedata.normalize("NFKC", str(text))
    norm = norm.casefold()
    norm = re.sub(r"\s+", " ", norm).strip()
    return norm


def clean_attribute_value(val: str) -> str:
    """Cleans punctuation and extra formatting from an attribute value string."""
    cleaned = normalize_str(val)
    cleaned = re.sub(r"^[^\w\d]+|[^\w\d]+$", "", cleaned)
    return cleaned


class CatalogAttributeExtractor:
    """Extracts structured and unstructured attributes from raw product dictionaries."""

    def __init__(self) -> None:
        # Precompile lexicon word-boundary regexes
        self._material_patterns = {
            mat: re.compile(rf"\b{re.escape(mat)}\b", re.IGNORECASE) for mat in MATERIAL_LEXICON
        }
        self._color_patterns = {
            col: re.compile(rf"\b{re.escape(col)}\b", re.IGNORECASE) for col in COLOR_LEXICON
        }
        self._gender_patterns = {
            gen: re.compile(rf"\b{re.escape(gen)}\b", re.IGNORECASE) for gen in GENDER_LEXICON
        }
        self._style_patterns = {
            sty: re.compile(rf"\b{re.escape(sty)}\b", re.IGNORECASE) for sty in STYLE_LEXICON
        }

    def extract(
        self,
        raw_product: Mapping[str, Any],
        search_fields: Mapping[str, str],
    ) -> tuple[dict[str, frozenset[str]], dict[str, tuple[AttributeEvidence, ...]]]:
        """Extracts all attributes and provenance evidence for a product record."""
        attributes_map: dict[str, set[str]] = defaultdict(set)
        evidence_map: dict[str, list[AttributeEvidence]] = defaultdict(list)

        # 1. Extract from structured details mapping
        details = raw_product.get("details")
        if isinstance(details, dict):
            for raw_k, raw_v in details.items():
                if raw_v is None:
                    continue
                k_norm = normalize_str(str(raw_k))
                v_norm = clean_attribute_value(str(raw_v))
                if not v_norm:
                    continue

                matched_attr = STRUCTURED_KEY_MAPPING.get(k_norm)
                if matched_attr is not None:
                    attr_name = matched_attr.value
                    # Split comma, slash, or semicolon separated items
                    parts = [clean_attribute_value(p) for p in re.split(r"[,;/|]", v_norm) if clean_attribute_value(p)]
                    for p in parts:
                        attributes_map[attr_name].add(p)
                        evidence_map[attr_name].append(
                            AttributeEvidence(
                                value=p,
                                source_field=f"details.{raw_k}",
                                extraction="structured",
                                confidence=0.98,
                            )
                        )
                        # Strip percentage prefixes like "100% cotton" -> "cotton"
                        stripped = re.sub(r"^\d+(?:\.\d+)?%\s*", "", p).strip()
                        if stripped and stripped != p:
                            attributes_map[attr_name].add(stripped)
                            evidence_map[attr_name].append(
                                AttributeEvidence(
                                    value=stripped,
                                    source_field=f"details.{raw_k}",
                                    extraction="structured",
                                    confidence=0.98,
                                )
                            )

                        # Match against specific lexicon tokens if applicable
                        if attr_name == Attribute.MATERIAL.value:
                            for mat, pat in self._material_patterns.items():
                                if pat.search(p) and mat not in attributes_map[attr_name]:
                                    attributes_map[attr_name].add(mat)
                                    evidence_map[attr_name].append(
                                        AttributeEvidence(value=mat, source_field=f"details.{raw_k}", extraction="structured", confidence=0.98)
                                    )
                        elif attr_name == Attribute.COLOR.value:
                            for col, pat in self._color_patterns.items():
                                if pat.search(p) and col not in attributes_map[attr_name]:
                                    attributes_map[attr_name].add(col)
                                    evidence_map[attr_name].append(
                                        AttributeEvidence(value=col, source_field=f"details.{raw_k}", extraction="structured", confidence=0.98)
                                    )
                        elif attr_name == Attribute.STYLE.value:
                            for sty, pat in self._style_patterns.items():
                                if pat.search(p) and sty not in attributes_map[attr_name]:
                                    attributes_map[attr_name].add(sty)
                                    evidence_map[attr_name].append(
                                        AttributeEvidence(value=sty, source_field=f"details.{raw_k}", extraction="structured", confidence=0.98)
                                    )
                else:
                    # Generic detail key
                    attributes_map[k_norm].add(v_norm)
                    evidence_map[k_norm].append(
                        AttributeEvidence(
                            value=v_norm,
                            source_field=f"details.{raw_k}",
                            extraction="structured",
                            confidence=0.90,
                        )
                    )

        # 2. Extract store as brand
        store = raw_product.get("store")
        if store and isinstance(store, str):
            store_norm = clean_attribute_value(store)
            if store_norm and store_norm not in {"unknown", "n/a", "generic"}:
                attributes_map[Attribute.BRAND.value].add(store_norm)
                evidence_map[Attribute.BRAND.value].append(
                    AttributeEvidence(
                        value=store_norm,
                        source_field="store",
                        extraction="structured",
                        confidence=0.95,
                    )
                )

        # 3. Scan unstructured text fields (title, features, description)
        title_text = search_fields.get("title", "")
        features_text = search_fields.get("features", "")
        desc_text = search_fields.get("description", "")
        combined_text = f"{title_text} {features_text} {desc_text}"

        # Materials
        for mat, pat in self._material_patterns.items():
            if pat.search(title_text):
                attributes_map[Attribute.MATERIAL.value].add(mat)
                evidence_map[Attribute.MATERIAL.value].append(
                    AttributeEvidence(value=mat, source_field="title", extraction="text_rule", confidence=0.95)
                )
            elif pat.search(features_text):
                attributes_map[Attribute.MATERIAL.value].add(mat)
                evidence_map[Attribute.MATERIAL.value].append(
                    AttributeEvidence(value=mat, source_field="features", extraction="text_rule", confidence=0.88)
                )

        # Colors
        for col, pat in self._color_patterns.items():
            if pat.search(title_text):
                attributes_map[Attribute.COLOR.value].add(col)
                evidence_map[Attribute.COLOR.value].append(
                    AttributeEvidence(value=col, source_field="title", extraction="text_rule", confidence=0.95)
                )
            elif pat.search(features_text):
                attributes_map[Attribute.COLOR.value].add(col)
                evidence_map[Attribute.COLOR.value].append(
                    AttributeEvidence(value=col, source_field="features", extraction="text_rule", confidence=0.85)
                )

        # Styles / Features
        for sty, pat in self._style_patterns.items():
            if pat.search(title_text):
                attributes_map[Attribute.STYLE.value].add(sty)
                evidence_map[Attribute.STYLE.value].append(
                    AttributeEvidence(value=sty, source_field="title", extraction="text_rule", confidence=0.90)
                )
            elif pat.search(features_text):
                attributes_map[Attribute.STYLE.value].add(sty)
                evidence_map[Attribute.STYLE.value].append(
                    AttributeEvidence(value=sty, source_field="features", extraction="text_rule", confidence=0.80)
                )

        # Genders / Audience
        for gen, pat in self._gender_patterns.items():
            if pat.search(title_text):
                attributes_map[Attribute.STYLE.value].add(gen)
                evidence_map[Attribute.STYLE.value].append(
                    AttributeEvidence(value=gen, source_field="title", extraction="text_rule", confidence=0.95)
                )

        frozen_attributes = {k: frozenset(v) for k, v in attributes_map.items()}
        frozen_evidence = {k: tuple(v) for k, v in evidence_map.items()}
        return frozen_attributes, frozen_evidence
