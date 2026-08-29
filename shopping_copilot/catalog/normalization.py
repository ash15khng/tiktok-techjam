"""Conservative text conversion shared by indexing and retrieval."""

from __future__ import annotations

import re
import unicodedata


TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "but", "by", "for",
        "from", "i", "in", "is", "it", "me", "my", "of", "on", "or",
        "please", "some", "that", "the", "this", "to", "want", "with",
        "would", "you", "looking", "those", "these", "options", "quite",
        "right", "yet", "ask", "about", "one", "specific", "attribute",
        "what", "matters", "key", "requirement", "still", "exploring",
        "actually", "ignore", "earlier", "preference", "additional", "need",
        "have", "your", "judgment", "here", "closest", "found", "item",
    }
)


def flatten_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return " ".join(f"{key} {item}" for key, item in value.items())
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value)


def string_values(value: object) -> tuple[str, ...]:
    if isinstance(value, dict):
        return tuple(f"{key} {item}" for key, item in value.items() if item not in (None, "", []))
    if isinstance(value, list):
        return tuple(str(item) for item in value if item not in (None, ""))
    return (str(value),) if value not in (None, "") else ()


def normalize_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def tokenize(value: str, *, drop_stopwords: bool = True) -> tuple[str, ...]:
    tokens = tuple(token.casefold() for token in TOKEN_RE.findall(normalize_text(value)))
    if not drop_stopwords:
        return tokens
    return tuple(token for token in tokens if len(token) > 1 and token not in STOPWORDS)
