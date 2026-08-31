"""Ground untrusted semantic hints before they can affect retrieval state."""

from __future__ import annotations

import re
from dataclasses import dataclass

from submission.src.catalog.normalization import normalize_text, tokenize
from submission.src.contracts import SemanticInterpretation, SemanticSlotHypothesis
from submission.src.understanding.models import Attribute, SlotUpdate


ASIN_RE = re.compile(r"\bB0[A-Z0-9]{8}\b", re.IGNORECASE)
NEGATION_RE = re.compile(r"\b(?:not|no|without|avoid|exclude|anything\s+but)\b", re.IGNORECASE)
SET_ANY_RE = re.compile(
    r"\b(?:no\s+(?:preference|budget)|don.?t\s+care|doesn.?t\s+matter|any\s+is\s+fine)\b",
    re.IGNORECASE,
)
SEMANTIC_OPERATIONS = frozenset({"add", "replace", "exclude", "set_any"})
WHITESPACE_RE = re.compile(r"\s+")
# Raising this admits richer model hypotheses but increases semantic drift;
# lowering it rejects long yet potentially useful needs. Eight terms retained
# grounded hard-suite behavior; no isolated sweep is claimed.
MAX_SEMANTIC_HYPOTHESIS_TERMS = 8


@dataclass(frozen=True)
class GroundedSemantic:
    """Validated model evidence allowed to cross into deterministic state."""

    query_rewrites: tuple[str, ...] = ()
    subjective_needs: tuple[str, ...] = ()
    slot_hypotheses: tuple[SemanticSlotHypothesis, ...] = ()
    slot_updates: tuple[SlotUpdate, ...] = ()
    preference_phrases: tuple[str, ...] = ()
    category_phrases: tuple[str, ...] = ()
    exclusions: tuple[str, ...] = ()


def ground_semantic_interpretation(
    semantic: SemanticInterpretation,
    *,
    raw_message: str,
    context: str,
    deterministic_updates: tuple[SlotUpdate, ...],
    override: bool,
    min_confidence: float,
    max_rewrite_terms: int,
) -> GroundedSemantic:
    """Keep only bounded hints anchored to current participant-visible text."""

    anchor_text = raw_message if override else f"{raw_message} {context}"
    anchor_terms = set(tokenize(anchor_text))
    query_rewrites = tuple(
        dict.fromkeys(
            cleaned
            for value in semantic.query_rewrites
            if (cleaned := _safe_rewrite(value, anchor_terms, max_rewrite_terms))
        )
    )
    subjective_needs = tuple(
        dict.fromkeys(
            cleaned
            for value in semantic.subjective_needs
            if (cleaned := _safe_observation(value, anchor_terms, max_rewrite_terms))
        )
    )

    deterministic_attributes = {
        update.attribute
        for update in deterministic_updates
        if update.source not in {"fallback", "semantic"}
    }
    retained: list[SemanticSlotHypothesis] = []
    updates: list[SlotUpdate] = []
    preferences: list[str] = []
    categories: list[str] = []
    exclusions: list[str] = []
    seen: set[tuple[Attribute, str]] = set()
    for hypothesis in semantic.slot_hypotheses:
        try:
            attribute = Attribute(hypothesis.attribute)
        except ValueError:
            continue
        cleaned_value = _clean_phrase(hypothesis.value)
        key = (attribute, normalize_text(cleaned_value))
        operation = hypothesis.operation
        evidence_grounded = _evidence_is_grounded(hypothesis.evidence, raw_message)
        set_any = operation == "set_any"
        exclude = operation == "exclude"
        if (
            attribute is Attribute.OTHER
            or attribute in deterministic_attributes
            or operation not in SEMANTIC_OPERATIONS
            or hypothesis.confidence < min_confidence
            or (not set_any and not cleaned_value)
            or (set_any and bool(cleaned_value))
            or (
                cleaned_value
                and len(tokenize(cleaned_value, drop_stopwords=False))
                > MAX_SEMANTIC_HYPOTHESIS_TERMS
            )
            or ASIN_RE.search(cleaned_value)
            or (not exclude and not set_any and NEGATION_RE.search(cleaned_value))
            or not evidence_grounded
            or (set_any and not SET_ANY_RE.search(hypothesis.evidence))
            or (exclude and not NEGATION_RE.search(hypothesis.evidence))
            or (
                not set_any
                and attribute
                not in {Attribute.FEATURE, Attribute.STYLE, Attribute.USE_CASE}
                and not _value_is_grounded(cleaned_value, hypothesis.evidence)
            )
            or key in seen
        ):
            continue
        seen.add(key)
        retained.append(hypothesis)
        if exclude:
            exclusions.append(cleaned_value)
        elif attribute is Attribute.CATEGORY:
            categories.append(cleaned_value)
        elif not set_any:
            preferences.append(cleaned_value)
        updates.append(
            SlotUpdate(
                attribute,
                operation,
                cleaned_value,
                hypothesis.evidence,
                "semantic",
            )
        )
    return GroundedSemantic(
        query_rewrites=query_rewrites,
        subjective_needs=subjective_needs,
        slot_hypotheses=tuple(retained),
        slot_updates=tuple(updates),
        preference_phrases=tuple(dict.fromkeys(preferences)),
        category_phrases=tuple(dict.fromkeys(categories)),
        exclusions=tuple(dict.fromkeys(exclusions)),
    )


def _safe_rewrite(value: str, anchor_terms: set[str], max_terms: int) -> str:
    cleaned = _clean_phrase(value)
    terms = tokenize(cleaned)
    if (
        not cleaned
        or not terms
        or len(terms) > max(1, max_terms)
        or ASIN_RE.search(cleaned)
        or NEGATION_RE.search(cleaned)
        or not anchor_terms.intersection(terms)
    ):
        return ""
    return cleaned


def _safe_observation(value: str, anchor_terms: set[str], max_terms: int) -> str:
    cleaned = _clean_phrase(value)
    terms = tokenize(cleaned)
    if (
        not cleaned
        or not terms
        or len(terms) > max(1, max_terms)
        or ASIN_RE.search(cleaned)
        or not anchor_terms.intersection(terms)
    ):
        return ""
    return cleaned


def _evidence_is_grounded(evidence: str, raw_message: str) -> bool:
    evidence_terms = tokenize(evidence, drop_stopwords=False)
    message_terms = tokenize(raw_message, drop_stopwords=False)
    if not evidence_terms or len(evidence_terms) > len(message_terms):
        return False
    width = len(evidence_terms)
    return any(
        message_terms[index : index + width] == evidence_terms
        for index in range(len(message_terms) - width + 1)
    )


def _value_is_grounded(value: str, evidence: str) -> bool:
    """Require hard attribute values to occur in the quoted customer span."""

    value_terms = set(tokenize(value, drop_stopwords=False))
    evidence_terms = set(tokenize(evidence, drop_stopwords=False))
    return bool(value_terms) and value_terms.issubset(evidence_terms)


def _clean_phrase(value: str) -> str:
    return WHITESPACE_RE.sub(" ", str(value)).strip(" -;,.\t\r\n")
