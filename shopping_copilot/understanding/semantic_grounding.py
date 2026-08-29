"""Ground untrusted semantic hints before they can affect retrieval state."""

from __future__ import annotations

import re
from dataclasses import dataclass

from shopping_copilot.catalog.normalization import normalize_text, tokenize
from shopping_copilot.contracts import SemanticInterpretation, SemanticSlotHypothesis
from shopping_copilot.understanding.models import Attribute, SlotUpdate


ASIN_RE = re.compile(r"\bB0[A-Z0-9]{8}\b", re.IGNORECASE)
NEGATION_RE = re.compile(r"\b(?:not|no|without|avoid|exclude|anything\s+but)\b", re.IGNORECASE)
SOFT_SEMANTIC_ATTRIBUTES = frozenset({Attribute.FEATURE, Attribute.STYLE, Attribute.USE_CASE})


@dataclass(frozen=True)
class GroundedSemantic:
    query_rewrites: tuple[str, ...] = ()
    subjective_needs: tuple[str, ...] = ()
    slot_hypotheses: tuple[SemanticSlotHypothesis, ...] = ()
    slot_updates: tuple[SlotUpdate, ...] = ()
    preference_phrases: tuple[str, ...] = ()


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

    deterministic_attributes = {update.attribute for update in deterministic_updates}
    retained: list[SemanticSlotHypothesis] = []
    updates: list[SlotUpdate] = []
    preferences: list[str] = []
    seen: set[tuple[Attribute, str]] = set()
    for hypothesis in semantic.slot_hypotheses:
        try:
            attribute = Attribute(hypothesis.attribute)
        except ValueError:
            continue
        cleaned_value = _clean_phrase(hypothesis.value)
        key = (attribute, normalize_text(cleaned_value))
        if (
            attribute not in SOFT_SEMANTIC_ATTRIBUTES
            or attribute in deterministic_attributes
            or hypothesis.confidence < min_confidence
            or not cleaned_value
            or len(tokenize(cleaned_value, drop_stopwords=False)) > 8
            or ASIN_RE.search(cleaned_value)
            or NEGATION_RE.search(cleaned_value)
            or not _evidence_is_grounded(hypothesis.evidence, raw_message)
            or key in seen
        ):
            continue
        seen.add(key)
        retained.append(hypothesis)
        preferences.append(cleaned_value)
        updates.append(
            SlotUpdate(
                attribute,
                "replace" if override else "add",
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
    return any(message_terms[index : index + width] == evidence_terms for index in range(len(message_terms) - width + 1))


def _clean_phrase(value: str) -> str:
    return re.sub(r"\s+", " ", str(value)).strip(" -;,.\t\r\n")
