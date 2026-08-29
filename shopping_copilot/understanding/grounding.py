"""Catalog entity grounding, token trie matching, and conservative fuzzy linking."""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Mapping

from shopping_copilot.config import UnderstandingConfig
from shopping_copilot.understanding.models import (
    Attribute,
    InterpretationAmbiguity,
    Relation,
    SlotUpdate,
)

# ---------------------------------------------------------------------------
# Default Lexicons for e-Commerce Domain
# ---------------------------------------------------------------------------

DEFAULT_MATERIALS = {
    "cotton": "cotton",
    "organic cotton": "organic cotton",
    "polyester": "polyester",
    "poly": "polyester",
    "nylon": "nylon",
    "leather": "leather",
    "genuine leather": "leather",
    "faux leather": "faux leather",
    "synthetic leather": "faux leather",
    "wool": "wool",
    "merino wool": "merino wool",
    "spandex": "spandex",
    "elastane": "spandex",
    "silk": "silk",
    "rayon": "rayon",
    "viscose": "rayon",
    "fabric": "fabric",
    "linen": "linen",
    "denim": "denim",
    "fleece": "fleece",
    "canvas": "canvas",
    "mesh": "mesh",
    "velvet": "velvet",
    "suede": "suede",
    "faux suede": "faux suede",
    "cashmere": "cashmere",
    "satin": "satin",
    "chiffon": "chiffon",
    "bamboo": "bamboo",
    "modal": "modal",
    "rubber": "rubber",
    "eva": "eva",
    "down": "down",
    "gore-tex": "gore-tex",
}

DEFAULT_COLORS = {
    "black": "black",
    "white": "white",
    "blue": "blue",
    "navy": "navy",
    "navy blue": "navy",
    "light blue": "light blue",
    "dark blue": "dark blue",
    "royal blue": "royal blue",
    "red": "red",
    "dark red": "dark red",
    "pink": "pink",
    "hot pink": "hot pink",
    "baby pink": "baby pink",
    "green": "green",
    "olive": "olive",
    "olive green": "olive",
    "dark green": "dark green",
    "forest green": "forest green",
    "mint green": "mint green",
    "brown": "brown",
    "dark brown": "dark brown",
    "gray": "gray",
    "grey": "gray",
    "dark gray": "dark gray",
    "light gray": "light gray",
    "charcoal": "charcoal",
    "purple": "purple",
    "lavender": "lavender",
    "violet": "violet",
    "yellow": "yellow",
    "mustard": "mustard",
    "orange": "orange",
    "coral": "coral",
    "peach": "peach",
    "beige": "beige",
    "tan": "tan",
    "khaki": "khaki",
    "cream": "cream",
    "ivory": "ivory",
    "gold": "gold",
    "silver": "silver",
    "bronze": "bronze",
    "burgundy": "burgundy",
    "maroon": "maroon",
    "wine": "burgundy",
    "teal": "teal",
    "turquoise": "turquoise",
    "multi": "multi",
    "multicolor": "multicolor",
    "rainbow": "rainbow",
}

DEFAULT_CATEGORIES = {
    "shoe": "shoes",
    "shoes": "shoes",
    "running shoe": "running shoes",
    "running shoes": "running shoes",
    "walking shoe": "walking shoes",
    "walking shoes": "walking shoes",
    "sneaker": "sneakers",
    "sneakers": "sneakers",
    "boot": "boots",
    "boots": "boots",
    "winter boot": "winter boots",
    "winter boots": "winter boots",
    "hiking boot": "hiking boots",
    "hiking boots": "hiking boots",
    "sandal": "sandals",
    "sandals": "sandals",
    "slipper": "slippers",
    "slippers": "slippers",
    "loafer": "loafers",
    "loafers": "loafers",
    "heel": "heels",
    "heels": "heels",
    "shirt": "shirts",
    "shirts": "shirts",
    "t-shirt": "t-shirts",
    "t-shirts": "t-shirts",
    "tshirt": "t-shirts",
    "tshirts": "t-shirts",
    "tee": "t-shirts",
    "tees": "t-shirts",
    "dress shirt": "dress shirts",
    "polo": "polo shirts",
    "polo shirt": "polo shirts",
    "blouse": "blouses",
    "blouses": "blouses",
    "top": "tops",
    "tops": "tops",
    "tank top": "tank tops",
    "tank": "tank tops",
    "hoodie": "hoodies",
    "hoodies": "hoodies",
    "sweatshirt": "sweatshirts",
    "sweater": "sweaters",
    "sweaters": "sweaters",
    "cardigan": "cardigans",
    "jacket": "jackets",
    "jackets": "jackets",
    "coat": "coats",
    "coats": "coats",
    "winter coat": "winter coats",
    "rain jacket": "rain jackets",
    "windbreaker": "windbreakers",
    "vest": "vests",
    "blazer": "blazers",
    "pants": "pants",
    "trouser": "pants",
    "trousers": "pants",
    "jeans": "jeans",
    "denim jeans": "jeans",
    "shorts": "shorts",
    "leggings": "leggings",
    "sweatpants": "sweatpants",
    "joggers": "joggers",
    "skirt": "skirts",
    "skirts": "skirts",
    "dress": "dresses",
    "dresses": "dresses",
    "maxi dress": "maxi dresses",
    "midi dress": "midi dresses",
    "sock": "socks",
    "socks": "socks",
    "hat": "hats",
    "hats": "hats",
    "cap": "caps",
    "beanie": "beanies",
    "glove": "gloves",
    "gloves": "gloves",
    "mittens": "mittens",
    "scarf": "scarves",
    "scarves": "scarves",
    "belt": "belts",
    "watch": "watches",
    "sunglasses": "sunglasses",
    "backpack": "backpacks",
    "bag": "bags",
    "tote bag": "tote bags",
    "purse": "purses",
    "handbag": "handbags",
    "wallet": "wallets",
}

DEFAULT_STYLES = {
    "slim fit": "slim fit",
    "regular fit": "regular fit",
    "relaxed fit": "relaxed fit",
    "loose fit": "loose fit",
    "oversized": "oversized",
    "tight fit": "tight fit",
    "athletic fit": "athletic fit",
    "crew neck": "crew neck",
    "crewneck": "crew neck",
    "v-neck": "v-neck",
    "v neck": "v-neck",
    "round neck": "round neck",
    "turtleneck": "turtleneck",
    "collared": "collared",
    "button down": "button down",
    "button up": "button down",
    "short sleeve": "short sleeve",
    "long sleeve": "long sleeve",
    "sleeveless": "sleeveless",
    "high waist": "high waist",
    "high waisted": "high waist",
    "mid rise": "mid rise",
    "low rise": "low rise",
    "ankle length": "ankle length",
    "cropped": "cropped",
    "knee length": "knee length",
    "zipper": "zipper closure",
    "zip up": "zipper closure",
    "pullover": "pullover",
    "lace up": "lace up",
    "slip on": "slip on",
    "casual": "casual",
    "formal": "formal",
    "vintage": "vintage",
    "boho": "boho",
    "minimalist": "minimalist",
}

DEFAULT_USE_CASES = {
    "hiking": "hiking",
    "running": "running",
    "walking": "walking",
    "gym": "gym",
    "workout": "workout",
    "training": "training",
    "fitness": "fitness",
    "yoga": "yoga",
    "cycling": "cycling",
    "swimming": "swimming",
    "winter": "winter",
    "summer": "summer",
    "outdoor": "outdoor",
    "outdoors": "outdoor",
    "indoor": "indoor",
    "work": "work",
    "office": "office",
    "business": "business",
    "travel": "travel",
    "party": "party",
    "everyday": "everyday",
    "daily wear": "everyday",
    "athletic": "athletic",
    "sports": "sports",
    "climbing": "climbing",
    "camping": "camping",
    "trail": "trail",
}

DEFAULT_FEATURES = {
    "waterproof": "waterproof",
    "water resistant": "water resistant",
    "water-repellent": "water-repellent",
    "breathable": "breathable",
    "lightweight": "lightweight",
    "heavyweight": "heavyweight",
    "thermal": "thermal",
    "insulated": "insulated",
    "warm": "warm",
    "windproof": "windproof",
    "quick dry": "quick dry",
    "quick-drying": "quick dry",
    "moisture wicking": "moisture wicking",
    "stretchy": "stretch",
    "elastic": "elastic",
    "cushioned": "cushioned",
    "arch support": "arch support",
    "memory foam": "memory foam",
    "non-slip": "non-slip",
    "slip resistant": "slip resistant",
    "wrinkle free": "wrinkle free",
    "durable": "durable",
    "pockets": "pockets",
    "hooded": "hooded",
}


def normalize_token(token: str) -> str:
    """Normalize a token using Unicode NFKC, lowercasing, and stripping punctuation."""
    norm = unicodedata.normalize("NFKC", token).casefold()
    return re.sub(r"[^\w\s-]", "", norm).strip()


@dataclass
class TrieNode:
    children: dict[str, TrieNode] = field(default_factory=dict)
    # Mapping of Attribute -> normalized value
    matches: dict[Attribute, str] = field(default_factory=dict)


class CatalogTrie:
    """Token trie for fast longest-match entity extraction over catalog aliases."""

    def __init__(self) -> None:
        self.root = TrieNode()

    def insert(self, phrase: str, attribute: Attribute, canonical_value: str) -> None:
        tokens = [normalize_token(t) for t in phrase.split() if normalize_token(t)]
        if not tokens:
            return
        curr = self.root
        for token in tokens:
            if token not in curr.children:
                curr.children[token] = TrieNode()
            curr = curr.children[token]
        curr.matches[attribute] = canonical_value

    def scan(self, text: str) -> list[tuple[Attribute, str, str, tuple[int, int]]]:
        """Scan text and return longest matches (Attribute, canonical_value, raw_span, char_span)."""
        # Tokenize with character spans
        token_matches = list(re.finditer(r"[\w-]+", text))
        tokens = [normalize_token(m.group(0)) for m in token_matches]
        results: list[tuple[Attribute, str, str, tuple[int, int]]] = []

        i = 0
        while i < len(tokens):
            curr = self.root
            longest_match: tuple[Attribute, str, int] | None = None  # (attr, canonical, end_idx)
            for j in range(i, len(tokens)):
                tok = tokens[j]
                if tok in curr.children:
                    curr = curr.children[tok]
                    if curr.matches:
                        # Grab first matching attribute (or all)
                        for attr, canonical in curr.matches.items():
                            longest_match = (attr, canonical, j)
                else:
                    break

            if longest_match:
                attr, canonical, end_idx = longest_match
                start_char = token_matches[i].start()
                end_char = token_matches[end_idx].end()
                raw_span = text[start_char:end_char]
                results.append((attr, canonical, raw_span, (start_char, end_char)))
                i = end_idx + 1
            else:
                i += 1

        return results


def build_default_trie() -> CatalogTrie:
    """Construct and seed a CatalogTrie with standard eCommerce aliases."""
    trie = CatalogTrie()
    for phrase, canonical in DEFAULT_MATERIALS.items():
        trie.insert(phrase, Attribute.MATERIAL, canonical)
    for phrase, canonical in DEFAULT_COLORS.items():
        trie.insert(phrase, Attribute.COLOR, canonical)
    for phrase, canonical in DEFAULT_CATEGORIES.items():
        trie.insert(phrase, Attribute.CATEGORY, canonical)
    for phrase, canonical in DEFAULT_STYLES.items():
        trie.insert(phrase, Attribute.STYLE, canonical)
    for phrase, canonical in DEFAULT_USE_CASES.items():
        trie.insert(phrase, Attribute.USE_CASE, canonical)
    for phrase, canonical in DEFAULT_FEATURES.items():
        trie.insert(phrase, Attribute.FEATURE, canonical)
    return trie


class CatalogEntityLinker:
    """Conservative entity linking with Jaccard, SequenceMatcher, and category gating."""

    def __init__(
        self,
        config: UnderstandingConfig,
        known_values_by_attribute: Mapping[Attribute, set[str]] | None = None,
    ) -> None:
        self.config = config
        self.known_values: dict[Attribute, set[str]] = (
            {k: set(v) for k, v in known_values_by_attribute.items()}
            if known_values_by_attribute
            else {
                Attribute.MATERIAL: set(DEFAULT_MATERIALS.values()),
                Attribute.COLOR: set(DEFAULT_COLORS.values()),
                Attribute.CATEGORY: set(DEFAULT_CATEGORIES.values()),
                Attribute.STYLE: set(DEFAULT_STYLES.values()),
                Attribute.USE_CASE: set(DEFAULT_USE_CASES.values()),
                Attribute.FEATURE: set(DEFAULT_FEATURES.values()),
            }
        )

    def link_span(
        self,
        span: str,
        target_attribute: Attribute,
        category_hint: str | None = None,
    ) -> tuple[str | None, float, InterpretationAmbiguity | None]:
        """Attempt to fuzzy-link an unmatched span to a known attribute value."""
        norm_span = normalize_token(span)
        if len(norm_span) <= 2 and target_attribute != Attribute.SIZE:
            # Never fuzzy link short 1-2 char strings without size context
            return None, 0.0, None

        candidates = self.known_values.get(target_attribute, set())
        if not candidates:
            return None, 0.0, None

        scored_candidates: list[tuple[float, str]] = []
        span_tokens = set(norm_span.split())

        for candidate in candidates:
            cand_norm = normalize_token(candidate)
            cand_tokens = set(cand_norm.split())

            # 1. Token / N-gram Jaccard
            inter = len(span_tokens.intersection(cand_tokens))
            union = len(span_tokens.union(cand_tokens))
            tok_jaccard = inter / union if union > 0 else 0.0

            # Character 2-gram Jaccard for spelling/typos
            if len(norm_span) >= 2 and len(cand_norm) >= 2:
                ng1 = {norm_span[i:i+2] for i in range(len(norm_span) - 1)}
                ng2 = {cand_norm[i:i+2] for i in range(len(cand_norm) - 1)}
                char_jaccard = len(ng1 & ng2) / len(ng1 | ng2) if (ng1 | ng2) else 0.0
            else:
                char_jaccard = 1.0 if norm_span == cand_norm else 0.0

            jaccard = max(tok_jaccard, char_jaccard)

            # 2. SequenceMatcher ratio
            seq_ratio = difflib.SequenceMatcher(None, norm_span, cand_norm).ratio()

            # 3. Category compatibility (placeholder neutral 1.0 or higher if aligned)
            cat_compat = 1.0

            score = 0.55 * jaccard + 0.25 * seq_ratio + 0.20 * cat_compat
            scored_candidates.append((score, candidate))

        scored_candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, best_cand = scored_candidates[0]

        if best_score >= self.config.fuzzy_min_score:
            margin = (
                best_score - scored_candidates[1][0]
                if len(scored_candidates) > 1
                else 1.0
            )
            if margin >= self.config.fuzzy_min_margin:
                return best_cand, best_score, None
            else:
                ambiguity = InterpretationAmbiguity(
                    raw_span=span,
                    candidate_attributes=(target_attribute,),
                    candidate_values=tuple(c[1] for c in scored_candidates[:3]),
                    reason=f"Close competing candidates with margin {margin:.3f} < {self.config.fuzzy_min_margin}",
                )
                return None, best_score, ambiguity

        return None, 0.0, None
