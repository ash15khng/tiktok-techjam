"""Deterministic message interpretation with an optional semantic boundary."""

from __future__ import annotations

import re

from shopping_copilot.catalog.normalization import normalize_text, tokenize
from shopping_copilot.contracts import DisabledSemanticParser, SemanticParser
from shopping_copilot.understanding.models import Attribute, IntentFrame, SlotUpdate


CATEGORY_RE = re.compile(
    r"\b(?:looking\s+for|searching\s+for|want|need)\s+(.+?)(?=\s*,\s*(?:but|and)\b|[.!?]|$)",
    re.IGNORECASE,
)
PAYLOAD_RE = re.compile(
    r"(?:key\s+requirement\s+is|what\s+matters\s+is|what\s+i\s+need\s+is)\s*:\s*(.+)",
    re.IGNORECASE,
)
NO_PREFERENCE_RE = re.compile(
    r"(?:don['’]?t|do\s+not)\s+have\s+(?:an?\s+|any\s+)?(?:additional\s+)?preference\s+for\s+([a-z_]+)",
    re.IGNORECASE,
)

MATERIALS = frozenset(("cotton", "polyester", "nylon", "leather", "wool", "spandex", "silk", "rayon", "fabric"))
COLORS = frozenset(("black", "white", "blue", "red", "pink", "green", "brown", "gray", "grey", "purple", "yellow", "orange", "navy"))
USE_CASES = frozenset(("hiking", "running", "gym", "winter", "outdoor", "work", "wedding", "travel", "sports"))


def _attribute_for(text: str) -> Attribute:
    terms = set(tokenize(text, drop_stopwords=False))
    lowered = normalize_text(text)
    if "budget" in terms or "$" in text or re.search(r"\b(?:under|below|over|around)\s+\d", lowered):
        return Attribute.BUDGET
    if terms & MATERIALS:
        return Attribute.MATERIAL
    if terms & COLORS or "color" in terms or "colour" in terms:
        return Attribute.COLOR
    if terms & USE_CASES:
        return Attribute.USE_CASE
    if terms & {"size", "sizing", "width", "wide", "narrow", "small", "medium", "large", "xl", "xxl"}:
        return Attribute.SIZE
    if terms & {"style", "fit", "sleeve", "neck", "closure", "department"}:
        return Attribute.STYLE
    if "brand" in terms:
        return Attribute.BRAND
    return Attribute.FEATURE


def _clean_phrase(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" -;,.:\t\r\n")


class MessageInterpreter:
    def __init__(self, semantic_parser: SemanticParser | None = None) -> None:
        self.semantic_parser = semantic_parser or DisabledSemanticParser()

    def parse(self, message: str, *, last_ask_attribute: str | None, context: str) -> IntentFrame:
        raw = str(message or "")
        lowered = normalize_text(raw)
        override = bool(re.search(r"\b(?:actually|instead|ignore\s+(?:my\s+)?earlier|make\s+it)\b", lowered))
        negative_feedback = bool(
            re.search(r"\b(?:not\s+quite\s+right|ask\s+me\s+about|no\s+preference|don['’]?t\s+have)\b", lowered)
        )
        no_preference: Attribute | None = None
        no_preference_match = NO_PREFERENCE_RE.search(raw)
        if no_preference_match:
            try:
                no_preference = Attribute(no_preference_match.group(1).casefold())
            except ValueError:
                no_preference = Attribute.OTHER
        elif re.search(r"\b(?:no\s+preference|either\s+is\s+fine|use\s+your\s+judgment)\b", lowered):
            try:
                no_preference = Attribute(last_ask_attribute) if last_ask_attribute else Attribute.OTHER
            except ValueError:
                no_preference = Attribute.OTHER

        categories: list[str] = []
        category_match = CATEGORY_RE.search(raw)
        if category_match:
            category = _clean_phrase(category_match.group(1))
            if category and not category.casefold().startswith("is:"):
                categories.append(category)

        preferences: list[str] = []
        payload_match = PAYLOAD_RE.search(raw)
        if payload_match:
            preferences.extend(
                phrase
                for phrase in (_clean_phrase(part) for part in payload_match.group(1).split(";"))
                if phrase
            )
        elif category_match:
            tail = _clean_phrase(raw[category_match.end():])
            tail = re.sub(
                r"^(?:but\s+)?(?:i['’]?m|i\s+am)\s+still\s+exploring\.?$",
                "",
                tail,
                flags=re.IGNORECASE,
            )
            if tail and not no_preference:
                preferences.append(tail)
        elif not no_preference and not re.search(r"ask\s+me\s+about\s+one\s+specific\s+attribute", lowered):
            cleaned = _clean_phrase(raw)
            if cleaned:
                preferences.append(cleaned)

        exclusions: list[str] = []
        retained_preferences: list[str] = []
        for phrase in preferences:
            negative = re.match(r"(?:not|without|avoid|anything\s+but)\s+(.+)", phrase, re.IGNORECASE)
            if negative:
                exclusions.append(_clean_phrase(negative.group(1)))
            else:
                retained_preferences.append(phrase)

        slot_updates: list[SlotUpdate] = [
            SlotUpdate(Attribute.CATEGORY, "replace" if override else "set", value, value)
            for value in categories
        ]
        slot_updates.extend(
            SlotUpdate(_attribute_for(value), "replace" if override else "add", value, value)
            for value in retained_preferences
        )
        slot_updates.extend(
            SlotUpdate(_attribute_for(value), "exclude", value, value)
            for value in exclusions
        )
        if no_preference:
            slot_updates.append(SlotUpdate(no_preference, "set_any", "", raw))

        semantic = self.semantic_parser.interpret(raw, context)
        dialogue_acts = ["inform"]
        if override:
            dialogue_acts.append("correct")
        if no_preference:
            dialogue_acts.append("decline")
        return IntentFrame(
            raw_message=raw,
            dialogue_acts=tuple(dialogue_acts),
            slot_updates=tuple(slot_updates),
            category_phrases=tuple(dict.fromkeys(categories)),
            preference_phrases=tuple(dict.fromkeys(retained_preferences)),
            exclusions=tuple(dict.fromkeys(exclusions)),
            override=override,
            negative_feedback=negative_feedback,
            no_preference_attribute=no_preference,
            query_rewrites=semantic.query_rewrites,
            subjective_needs=semantic.subjective_needs,
            prompt_tokens=semantic.prompt_tokens,
            completion_tokens=semantic.completion_tokens,
        )
