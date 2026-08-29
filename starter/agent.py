from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path


TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "i", "in", "is", "it", "me", "my", "of", "on", "or", "please", "some",
    "that", "the", "this", "to", "want", "with", "would", "you", "looking",
    "actually", "earlier", "preference", "prefer", "need", "item", "thing",
    "what", "matters", "have", "additional", "dont", "don", "for", "that",
    "still", "exploring", "quite", "right", "yet", "ask", "specific",
}
ATTRIBUTES = ("feature", "material", "color", "style", "size", "use_case", "budget", "brand", "category")
MATERIALS = {"cotton", "polyester", "nylon", "leather", "wool", "spandex", "silk", "rayon", "fabric"}
COLORS = {"black", "white", "blue", "red", "pink", "green", "brown", "gray", "grey", "purple", "yellow", "orange"}
ATTRIBUTE_HINTS = {
    "material": MATERIALS,
    "color": COLORS,
    "size": {"size", "sizing", "wide", "narrow", "small", "medium", "large"},
    "style": {"style", "fit", "sleeve", "neck", "closure", "casual", "formal"},
    "use_case": {"hiking", "running", "gym", "winter", "outdoor", "work", "walking"},
    "brand": {"brand", "manufacturer"},
    "budget": {"budget", "under", "below", "over", "dollar", "price"},
}


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return " ".join(f"{key} {item}" for key, item in value.items())
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value)


def _terms(text: str) -> list[str]:
    return [
        token.lower()
        for token in TOKEN_RE.findall(text)
        if len(token) > 1 and token.lower() not in STOPWORDS
    ]


@dataclass
class SessionState:
    general_terms: list[str] = field(default_factory=list)
    attribute_terms: dict[str, list[str]] = field(default_factory=dict)
    asked: set[str] = field(default_factory=set)
    any_attributes: set[str] = field(default_factory=set)
    last_ask: str | None = None


class Agent:
    """Deterministic conversational catalog search with isolated session state."""

    def __init__(self, catalog_path: str | Path = "data/catalog.jsonl") -> None:
        self.catalog_path = Path(catalog_path)
        self.connection = sqlite3.connect(":memory:")
        self._sessions: dict[str, SessionState] = {}
        self._products: dict[str, dict[str, object]] = {}
        self._build_index()

    def _build_index(self) -> None:
        cursor = self.connection.cursor()
        schema = "parent_asin UNINDEXED, title, categories, features, details, store, description"
        cursor.execute(f"CREATE VIRTUAL TABLE products USING fts5({schema}, tokenize='unicode61 remove_diacritics 2')")
        cursor.execute("CREATE VIRTUAL TABLE titles USING fts5(parent_asin UNINDEXED, title, tokenize='unicode61 remove_diacritics 2')")
        rows: list[tuple[str, str, str, str, str, str, str]] = []
        title_rows: list[tuple[str, str]] = []
        with self.catalog_path.open(encoding="utf-8") as handle:
            for line in handle:
                product = json.loads(line)
                asin = str(product["parent_asin"])
                title = _text(product.get("title"))
                rows.append((asin, title, _text(product.get("categories")), _text(product.get("features")),
                             _text(product.get("details")), _text(product.get("store")), _text(product.get("description"))))
                title_rows.append((asin, title))
                self._products[asin] = product
                if len(rows) >= 1000:
                    cursor.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
                    cursor.executemany("INSERT INTO titles VALUES (?, ?)", title_rows)
                    rows.clear()
                    title_rows.clear()
        if rows:
            cursor.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
            cursor.executemany("INSERT INTO titles VALUES (?, ?)", title_rows)
        self.connection.commit()

    def reset(self, session_id: str, user_profile: dict) -> None:
        self._sessions[session_id] = SessionState()

    def _attribute(self, terms: list[str], message: str) -> str:
        lowered = message.lower()
        for attribute in ATTRIBUTES:
            if any(value in terms for value in ATTRIBUTE_HINTS.get(attribute, set())):
                return attribute
        if re.search(r"\$\s*\d|\b(?:under|below|over|at least)\s+\d", lowered):
            return "budget"
        return "feature"

    def _update_state(self, state: SessionState, message: str) -> None:
        terms = _terms(message)
        lowered = message.lower()
        if not terms:
            return
        if re.search(r"\b(?:no preference|either is fine|your judgment)\b", lowered):
            if state.last_ask:
                state.attribute_terms.pop(state.last_ask, None)
                state.any_attributes.add(state.last_ask)
            return
        correction = re.search(r"\b(?:actually|instead|ignore earlier|make it)\b", lowered)
        attribute = state.last_ask if state.last_ask and len(terms) <= 8 else self._attribute(terms, message)
        if correction:
            state.attribute_terms.pop(attribute, None)
            if attribute == "feature":
                state.general_terms = state.general_terms[: max(1, len(state.general_terms) // 2)]
        bucket = state.attribute_terms.setdefault(attribute, [])
        bucket.extend(term for term in terms if term not in bucket)
        if not state.general_terms:
            state.general_terms = terms[:]
        elif not correction:
            state.general_terms.extend(term for term in terms if term not in state.general_terms)

    def _query(self, terms: list[str], table: str, limit: int, require_all: bool = False) -> list[str]:
        safe_terms = list(dict.fromkeys(term for term in terms if term.isalnum()))[:32]
        if not safe_terms:
            return []
        joiner = " AND " if require_all else " OR "
        expression = joiner.join(f'"{term}"' for term in safe_terms)
        if table == "titles":
            query = "SELECT parent_asin FROM titles WHERE titles MATCH ? ORDER BY bm25(titles, 0.0, 6.0) LIMIT ?"
        else:
            query = ("SELECT parent_asin FROM products WHERE products MATCH ? ORDER BY "
                     "bm25(products, 0.0, 6.0, 4.0, 2.5, 2.5, 1.5, 1.0) LIMIT ?")
        return [str(row[0]) for row in self.connection.execute(query, (expression, limit))]

    def _rank(self, state: SessionState) -> list[str]:
        terms = list(dict.fromkeys(state.general_terms + [term for values in state.attribute_terms.values() for term in values]))
        title_ids = self._query(terms, "titles", 150)
        field_ids = self._query(terms, "products", 300)
        precise_title_ids = self._query(terms, "titles", 100, require_all=True)
        precise_field_ids = self._query(terms, "products", 150, require_all=True)
        ranks: dict[str, float] = {}
        for rank, asin in enumerate(title_ids, 1):
            ranks[asin] = ranks.get(asin, 0.0) + 0.65 / (60 + rank)
        for rank, asin in enumerate(field_ids, 1):
            ranks[asin] = ranks.get(asin, 0.0) + 0.35 / (60 + rank)
        for rank, asin in enumerate(precise_title_ids, 1):
            ranks[asin] = ranks.get(asin, 0.0) + 0.45 / (60 + rank)
        for rank, asin in enumerate(precise_field_ids, 1):
            ranks[asin] = ranks.get(asin, 0.0) + 0.20 / (60 + rank)
        for asin in ranks:
            product_text = _text(self._products[asin]).lower()
            matched_terms = {term for term in terms if term in product_text}
            match_bonus = min(len(matched_terms), 12) * 0.003
            hard_terms = [term for values in state.attribute_terms.values() for term in values]
            constraint_bonus = sum(0.006 for term in hard_terms if term in product_text)
            ranks[asin] += match_bonus + constraint_bonus
        return sorted(ranks, key=lambda asin: (-ranks[asin], asin))

    def _next_question(self, state: SessionState, turn: int) -> str | None:
        if turn >= 10:
            return None
        for attribute in ATTRIBUTES:
            if attribute not in state.asked and attribute not in state.any_attributes:
                state.asked.add(attribute)
                state.last_ask = attribute
                return attribute
        return None

    def respond(self, session_id: str, user_message: str, turn: int, top_k: int) -> dict:
        if session_id not in self._sessions:
            raise RuntimeError("reset must be called before respond")
        state = self._sessions[session_id]
        self._update_state(state, user_message)
        ranked = self._rank(state)
        ask_attribute = self._next_question(state, turn)
        recommendations = [{"parent_asin": asin} for asin in ranked[: min(top_k, 10)]]
        question = f"What matters most about the item's {ask_attribute}?" if ask_attribute else ""
        return {
            "message": f"Here are the closest matches. {question}" if question else "Here are the closest matches.",
            "ask_attribute": ask_attribute,
            "recommendations": recommendations,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        }
