"""Deterministic message interpretation with an optional semantic boundary."""

from __future__ import annotations

import re
from dataclasses import replace

from submission.src.catalog.attributes import AttributeValueResolver, EmptyAttributeResolver
from submission.src.catalog.normalization import normalize_text
from submission.src.contracts import DisabledSemanticParser, SemanticParser
from submission.src.understanding.contextual import (
    contextual_no_preference,
    resolve_reply_value,
)
from submission.src.understanding.models import Attribute, IntentFrame, SlotUpdate
from submission.src.understanding.semantic_grounding import ground_semantic_interpretation


CATEGORY_RE = re.compile(
    r"\b(?:looking\s+for|searching\s+for|want|need|make\s+that)\s+(.+?)"
    r"(?=\s*(?:,|[.!?]|$|\b(?:under|below|over|above|between|with|without|preferably|ideally)\b))",
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
OVERRIDE_RE = re.compile(
    r"\b(?:actually|instead|ignore\s+(?:my\s+)?earlier|make\s+it)\b",
    re.IGNORECASE,
)
NEGATIVE_FEEDBACK_RE = re.compile(
    r"\b(?:not\s+quite\s+right|ask\s+me\s+about|no\s+preference|"
    r"don['’]?t\s+have)\b",
    re.IGNORECASE,
)
CONTEXTUAL_NO_PREFERENCE_RE = re.compile(
    r"\b(?:no\s+preference|either\s+is\s+fine|use\s+your\s+judgment)\b",
    re.IGNORECASE,
)
EXPLORING_TAIL_RE = re.compile(
    r"^(?:but\s+)?(?:i['’]?m|i\s+am)\s+still\s+exploring\.?$",
    re.IGNORECASE,
)
SPECIFIC_ATTRIBUTE_PROMPT_RE = re.compile(
    r"ask\s+me\s+about\s+one\s+specific\s+attribute",
    re.IGNORECASE,
)
CATALOG_EXCLUSION_RE = re.compile(
    r"(?:not|without|avoid|anything\s+but)\s+(.+)",
    re.IGNORECASE,
)
CUSTOMER_EXCLUSION_RE = re.compile(
    r"(?:not|no|without|avoid|anything\s+but|i\s+don['’]?t\s+want)\s+(.+)",
    re.IGNORECASE,
)
WHITESPACE_RE = re.compile(r"\s+")
LEADING_CONNECTOR_RE = re.compile(r"^(?:but|and)\s+", re.IGNORECASE)
PREFERENCE_PREFIX_RE = re.compile(
    r"^(?:actually\s+)?(?:please\s+)?(?:i(?:'d|\s+would)?\s+prefer|i\s+prefer|"
    r"preferably|ideally|make\s+it|with)\s+",
    re.IGNORECASE,
)
TRAILING_INSTEAD_RE = re.compile(r"\s+instead$", re.IGNORECASE)
CUSTOMER_CLAUSE_SEPARATOR_RE = re.compile(r"\s*[,;]\s*")


def _clean_phrase(value: str) -> str:
    return WHITESPACE_RE.sub(" ", value).strip(" -;,.:\t\r\n")


def _clean_customer_clause(value: str) -> str:
    cleaned = _clean_phrase(value)
    if cleaned.casefold() in {"actually", "please"}:
        return ""
    cleaned = LEADING_CONNECTOR_RE.sub("", cleaned)
    cleaned = PREFERENCE_PREFIX_RE.sub("", cleaned)
    cleaned = TRAILING_INSTEAD_RE.sub("", cleaned)
    return _clean_phrase(cleaned)


def _split_customer_tail(value: str) -> tuple[str, ...]:
    """Split high-confidence user separators without fragmenting catalog payloads."""

    return tuple(
        clause
        for clause in (
            _clean_customer_clause(part)
            for part in CUSTOMER_CLAUSE_SEPARATOR_RE.split(value)
        )
        if clause
    )


class MessageInterpreter:
    """Convert one customer message into immutable, typed state proposals.

    ``parse_deterministic`` never performs network I/O. ``enrich_with_semantics``
    may add locally grounded model hints, but it cannot remove deterministic
    evidence or introduce catalog identifiers.
    """

    def __init__(
        self,
        semantic_parser: SemanticParser | None = None,
        *,
        semantic_min_confidence: float = 0.55,
        semantic_max_rewrite_terms: int = 12,
        attribute_resolver: AttributeValueResolver | None = None,
    ) -> None:
        self.semantic_parser = semantic_parser or DisabledSemanticParser()
        self.semantic_min_confidence = semantic_min_confidence
        self.semantic_max_rewrite_terms = semantic_max_rewrite_terms
        self.attribute_resolver = attribute_resolver or EmptyAttributeResolver()

    def parse(self, message: str, *, last_ask_attribute: str | None, context: str) -> IntentFrame:
        """Compatibility path: deterministic parse followed by normal semantic gating."""

        frame = self.parse_deterministic(message, last_ask_attribute=last_ask_attribute)
        return self.enrich_with_semantics(frame, context=context)

    def parse_deterministic(self, message: str, *, last_ask_attribute: str | None) -> IntentFrame:
        """Interpret a turn without invoking an optional provider."""

        raw = str(message or "")
        lowered = normalize_text(raw)
        override = bool(OVERRIDE_RE.search(lowered))
        negative_feedback = bool(NEGATIVE_FEEDBACK_RE.search(lowered))
        no_preference: Attribute | None = None
        no_preference_match = NO_PREFERENCE_RE.search(raw)
        if no_preference_match:
            try:
                no_preference = Attribute(no_preference_match.group(1).casefold())
            except ValueError:
                no_preference = Attribute.OTHER
        elif CONTEXTUAL_NO_PREFERENCE_RE.search(lowered):
            try:
                no_preference = Attribute(last_ask_attribute) if last_ask_attribute else Attribute.OTHER
            except ValueError:
                no_preference = Attribute.OTHER
        else:
            no_preference = contextual_no_preference(raw, last_ask_attribute)

        categories: list[str] = []
        category_match = CATEGORY_RE.search(raw)
        if category_match:
            category = _clean_phrase(category_match.group(1))
            if category and not category.casefold().startswith("is:"):
                categories.append(category)

        preferences: list[str] = []
        catalog_style_tail = False
        payload_match = PAYLOAD_RE.search(raw)
        if payload_match:
            preferences.extend(
                phrase
                for phrase in (_clean_phrase(part) for part in payload_match.group(1).split(";"))
                if phrase
            )
        elif category_match:
            raw_tail = raw[category_match.end():]
            tail = _clean_phrase(raw_tail)
            tail = EXPLORING_TAIL_RE.sub("", tail)
            if tail and not no_preference:
                # Evaluator/catalog-derived opening evidence follows a period
                # and may contain meaningful commas inside one product feature.
                # User-authored inline constraints are split conservatively.
                catalog_style_tail = raw_tail.lstrip().startswith(".")
                if catalog_style_tail:
                    preferences.append(tail)
                else:
                    preferences.extend(_split_customer_tail(tail))
        elif not no_preference and not SPECIFIC_ATTRIBUTE_PROMPT_RE.search(lowered):
            preferences.extend(_split_customer_tail(raw))

        exclusions: list[str] = []
        retained_preferences: list[str] = []
        for phrase in preferences:
            exclusion_pattern = (
                CATALOG_EXCLUSION_RE
                if payload_match or catalog_style_tail
                else CUSTOMER_EXCLUSION_RE
            )
            negative = exclusion_pattern.match(phrase)
            if negative:
                exclusions.append(_clean_phrase(negative.group(1)))
            else:
                retained_preferences.append(phrase)

        resolved_preferences = [
            (
                value,
                resolve_reply_value(
                    value,
                    last_ask_attribute=last_ask_attribute,
                    override=override,
                    resolver=self.attribute_resolver,
                ),
            )
            for value in retained_preferences
        ]
        resolved_exclusions = [
            (
                value,
                resolve_reply_value(
                    value,
                    last_ask_attribute=last_ask_attribute,
                    override=override,
                    resolver=self.attribute_resolver,
                ),
            )
            for value in exclusions
        ]
        resolved_categories = list(categories)
        preference_values: list[str] = []
        slot_updates: list[SlotUpdate] = [
            SlotUpdate(Attribute.CATEGORY, "replace" if override else "set", value, value)
            for value in categories
        ]
        for raw_value, resolved in resolved_preferences:
            if resolved.attribute is None or not resolved.value:
                continue
            if resolved.attribute is Attribute.CATEGORY:
                if resolved.value not in resolved_categories:
                    resolved_categories.append(resolved.value)
            else:
                preference_values.append(resolved.value)
            slot_updates.append(
                SlotUpdate(
                    resolved.attribute,
                    "replace" if override else "add",
                    resolved.value,
                    raw_value,
                    resolved.source,
                )
            )
        exclusion_values: list[str] = []
        for raw_value, resolved in resolved_exclusions:
            if resolved.attribute is None or not resolved.value:
                continue
            exclusion_values.append(resolved.value)
            slot_updates.append(
                SlotUpdate(resolved.attribute, "exclude", resolved.value, raw_value, resolved.source)
            )
        if no_preference:
            source = "explicit" if no_preference_match else "contextual"
            slot_updates.append(SlotUpdate(no_preference, "set_any", "", raw, source))

        dialogue_acts = ["inform"]
        if override:
            dialogue_acts.append("correct")
        if no_preference:
            dialogue_acts.append("decline")
        return IntentFrame(
            raw_message=raw,
            dialogue_acts=tuple(dialogue_acts),
            slot_updates=tuple(slot_updates),
            category_phrases=tuple(dict.fromkeys(resolved_categories)),
            preference_phrases=tuple(dict.fromkeys(preference_values)),
            exclusions=tuple(dict.fromkeys(exclusion_values)),
            override=override,
            negative_feedback=negative_feedback,
            no_preference_attribute=no_preference,
        )

    def enrich_with_semantics(
        self,
        frame: IntentFrame,
        *,
        context: str,
        force: bool = False,
    ) -> IntentFrame:
        """Return a semantic-enriched copy; deterministic evidence remains final."""

        interpret_eligible = getattr(self.semantic_parser, "interpret_eligible", None)
        if force and callable(interpret_eligible):
            semantic = interpret_eligible(frame.raw_message, context)
        else:
            semantic = self.semantic_parser.interpret(frame.raw_message, context)
        grounded_semantic = ground_semantic_interpretation(
            semantic,
            raw_message=frame.raw_message,
            context=context,
            deterministic_updates=frame.slot_updates,
            override=frame.override,
            min_confidence=self.semantic_min_confidence,
            max_rewrite_terms=self.semantic_max_rewrite_terms,
        )
        return replace(
            frame,
            slot_updates=(*frame.slot_updates, *grounded_semantic.slot_updates),
            preference_phrases=tuple(
                dict.fromkeys((*frame.preference_phrases, *grounded_semantic.preference_phrases))
            ),
            query_rewrites=grounded_semantic.query_rewrites,
            subjective_needs=grounded_semantic.subjective_needs,
            semantic_hypotheses=grounded_semantic.slot_hypotheses,
            prompt_tokens=semantic.prompt_tokens,
            completion_tokens=semantic.completion_tokens,
        )
