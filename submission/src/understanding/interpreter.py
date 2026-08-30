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
    r"(?:"
    r"(?:don.?t|do\s+not)\s+have\s+(?:an?\s+|any\s+)?(?:additional\s+)?"
    r"preference\s+for|"
    r"(?:don.?t|do\s+not)\s+care(?:\s+about)?|"
    r"no\s+preference\s+for|no"
    r")\s+(color|colour|material|size|style|brand|budget|feature|use[_\s-]?case)\b"
    r"(?:\s+(?:either|too))?",
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
    r"preferably|ideally|make\s+(?:it|the\s+\w+)|with)\s+",
    re.IGNORECASE,
)
TRAILING_INSTEAD_RE = re.compile(r"\s+instead$", re.IGNORECASE)
CUSTOMER_CLAUSE_SEPARATOR_RE = re.compile(r"\s*[,;]\s*")
CATEGORY_PRONOUN_RE = re.compile(r"^(?:it|them|this|that|those|these)\b", re.IGNORECASE)
DISCOURSE_ONLY_RE = re.compile(
    r"^(?:actually\s+)?(?:i\s+)?(?:want|need|prefer)(?:\s+it|\s+that)?$",
    re.IGNORECASE,
)
USE_CASE_PREFIX_RE = re.compile(r"^(?:for|to\s+wear\s+for)\s+", re.IGNORECASE)
ATTRIBUTE_ALIASES = {"colour": "color", "use case": "use_case", "use-case": "use_case"}

# Standalone interpreter defaults mirror AgentConfig. Raising confidence rejects
# more semantic slots; raising rewrite length accepts richer but riskier queries.
# The configured values passed the grounding suite; no isolated sweep is claimed.
DEFAULT_SEMANTIC_MIN_CONFIDENCE = 0.55
DEFAULT_SEMANTIC_MAX_REWRITE_TERMS = 12


def _clean_phrase(value: str) -> str:
    return WHITESPACE_RE.sub(" ", value).strip(" -;,.:\t\r\n")


def _clean_customer_clause(value: str) -> str:
    cleaned = _clean_phrase(value)
    if cleaned.casefold() in {"actually", "please"}:
        return ""
    cleaned = LEADING_CONNECTOR_RE.sub("", cleaned)
    cleaned = PREFERENCE_PREFIX_RE.sub("", cleaned)
    cleaned = TRAILING_INSTEAD_RE.sub("", cleaned)
    if DISCOURSE_ONLY_RE.fullmatch(cleaned):
        return ""
    return _clean_phrase(cleaned)


def _attribute_name(value: str) -> Attribute:
    """Normalize customer spelling to one competition attribute enum."""

    normalized = normalize_text(value).replace("_", " ").replace("-", " ")
    canonical = ATTRIBUTE_ALIASES.get(normalized, normalized.replace(" ", "_"))
    return Attribute(canonical)


def _remove_linked_modifier(category: str, modifier: str) -> str:
    """Remove one catalog-linked modifier while retaining the product noun."""

    pattern = re.compile(rf"\b{re.escape(modifier)}\b", re.IGNORECASE)
    reduced = _clean_phrase(pattern.sub(" ", category))
    return reduced or category


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
        semantic_min_confidence: float = DEFAULT_SEMANTIC_MIN_CONFIDENCE,
        semantic_max_rewrite_terms: int = DEFAULT_SEMANTIC_MAX_REWRITE_TERMS,
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
        """Interpret a turn without llm use yet."""

        raw = str(message or "")
        lowered = normalize_text(raw)
        override = bool(OVERRIDE_RE.search(lowered))
        negative_feedback = bool(NEGATIVE_FEEDBACK_RE.search(lowered))
        no_preference_matches = tuple(NO_PREFERENCE_RE.finditer(raw))
        no_preferences: list[Attribute] = []
        for match in no_preference_matches:
            try:
                attribute = _attribute_name(match.group(1))
            except ValueError:
                attribute = Attribute.OTHER
            if attribute not in no_preferences:
                no_preferences.append(attribute)
        no_preference = no_preferences[0] if no_preferences else None
        no_preference_match = no_preference_matches[0] if no_preference_matches else None

        if no_preference_match:
            pass
        elif CONTEXTUAL_NO_PREFERENCE_RE.search(lowered): # bare decline, saying they dont care, assumed to be the last asked attribute
            try:
                no_preference = (
                    Attribute(last_ask_attribute)
                    if last_ask_attribute
                    else Attribute.OTHER
                )
            except ValueError:
                no_preference = Attribute.OTHER
            no_preferences.append(no_preference)
        else: # cleans and check against bare decline again. returns None if no match
            no_preference = contextual_no_preference(raw, last_ask_attribute)
            if no_preference:
                no_preferences.append(no_preference)

        # Remove explicit Boundary spans before parsing positive evidence. This
        # keeps "no budget" from becoming a product exclusion and prevents a
        # trailing "don't care about colour" from becoming a false category.
        parseable_raw = NO_PREFERENCE_RE.sub(" ", raw)

        categories: list[str] = [] # finds category phrases in the message, e.g. "looking for running shoes" -> "running shoes"
        category_match = CATEGORY_RE.search(parseable_raw)
        if category_match:
            category = _clean_phrase(category_match.group(1))
            if (
                category
                and not category.casefold().startswith("is:")
                and not CATEGORY_PRONOUN_RE.match(category)
            ):
                categories.append(category)
            else:
                category_match = None

        preferences: list[str] = [] # finds preference phrases in the message, e.g. "I want red shoes" -> "red shoes"
        catalog_style_tail = False
        payload_match = PAYLOAD_RE.search(parseable_raw)
        if payload_match:
            preferences.extend(
                phrase
                for phrase in (_clean_phrase(part) for part in payload_match.group(1).split(";"))
                if phrase
            )
        elif category_match:
            raw_tail = parseable_raw[category_match.end():]
            tail = _clean_phrase(raw_tail)
            tail = EXPLORING_TAIL_RE.sub("", tail)
            if tail:
                # Evaluator/catalog-derived opening evidence follows a period
                # and may contain meaningful commas inside one product feature.
                # User-authored inline constraints are split conservatively.
                catalog_style_tail = raw_tail.lstrip().startswith(".")
                if catalog_style_tail:
                    preferences.append(tail)
                else:
                    preferences.extend(_split_customer_tail(tail))
        elif parseable_raw.strip(" ,;") and not SPECIFIC_ATTRIBUTE_PROMPT_RE.search(lowered):
            preferences.extend(_split_customer_tail(parseable_raw))

        # A leading "for ..." phrase is an occasion/use case. Removing only the
        # discourse prefix makes the stored value useful to catalog search.
        explicit_use_cases: list[str] = []
        for index, phrase in enumerate(preferences):
            if USE_CASE_PREFIX_RE.match(phrase):
                preferences[index] = _clean_phrase(USE_CASE_PREFIX_RE.sub("", phrase))
                if preferences[index]:
                    explicit_use_cases.append(preferences[index])

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
        matched_values = getattr(self.attribute_resolver, "matched_values", None)
        category_links: list[tuple[str, str]] = []
        resolved_categories: list[str] = []
        for category in categories:
            reduced_category = category
            if callable(matched_values):
                for attribute_name, value in matched_values(category):
                    if attribute_name == "category":
                        continue
                    category_links.append((attribute_name, value))
                    reduced_category = _remove_linked_modifier(reduced_category, value)
            resolved_categories.append(reduced_category)
        preference_values: list[str] = []
        slot_updates: list[SlotUpdate] = [
            SlotUpdate(Attribute.CATEGORY, "replace" if override else "set", value, value)
            for value in resolved_categories
        ]
        for value in explicit_use_cases:
            preference_values.append(value)
            slot_updates.append(
                SlotUpdate(
                    Attribute.USE_CASE,
                    "replace" if override else "add",
                    value,
                    value,
                    "explicit",
                )
            )
        # A catalog noun phrase can also carry explicit modifiers. Link those
        # modifiers independently so a later correction can replace only color
        # in "red shoes" without erasing size, budget, or use-case state.
        for attribute_name, value in category_links:
            try:
                attribute = Attribute(attribute_name)
            except ValueError:
                continue
            if value not in preference_values:
                preference_values.append(value)
            slot_updates.append(
                SlotUpdate(
                    attribute,
                    "replace" if override else "add",
                    value,
                    value,
                    "catalog_linked",
                )
            )
        for raw_value, resolved in resolved_preferences:
            if resolved.attribute is None or not resolved.value:
                continue
            if raw_value in explicit_use_cases:
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
                SlotUpdate(
                    resolved.attribute,
                    "exclude",
                    resolved.value,
                    raw_value,
                    resolved.source,
                )
            )
        for declined_attribute in no_preferences:
            source = "explicit" if no_preference_match else "contextual"
            slot_updates.append(SlotUpdate(declined_attribute, "set_any", "", raw, source))

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
            category_phrases=tuple(
                dict.fromkeys((*frame.category_phrases, *grounded_semantic.category_phrases))
            ),
            preference_phrases=tuple(
                dict.fromkeys((*frame.preference_phrases, *grounded_semantic.preference_phrases))
            ),
            exclusions=tuple(dict.fromkeys((*frame.exclusions, *grounded_semantic.exclusions))),
            query_rewrites=grounded_semantic.query_rewrites,
            subjective_needs=grounded_semantic.subjective_needs,
            semantic_hypotheses=grounded_semantic.slot_hypotheses,
            prompt_tokens=semantic.prompt_tokens,
            completion_tokens=semantic.completion_tokens,
        )
