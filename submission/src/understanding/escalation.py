"""Retrieval-aware decision boundary for optional semantic interpretation."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from threading import RLock

from submission.src.catalog.normalization import normalize_text, tokenize
from submission.src.config import AgentConfig
from submission.src.dialog.models import ActiveState
from submission.src.retrieval.models import RetrievalAssessment
from submission.src.understanding.models import IntentFrame
from submission.src.understanding.semantic import should_call_semantic_parser


@dataclass(frozen=True)
class SemanticEscalationDecision:
    """Whether one billed semantic call is justified and its reason code."""

    should_call: bool
    reason: str


class SemanticEscalationPolicy:
    """Call semantics only when language and deterministic evidence warrant it."""

    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self._lock = RLock()
        self._counts: Counter[str] = Counter()

    def decide(
        self,
        frame: IntentFrame,
        active: ActiveState,
        assessment: RetrievalAssessment,
        *,
        top_exact_preference_match: bool = False,
    ) -> SemanticEscalationDecision:
        """
        Gate a model call using language gaps and retrieval stability.
        no usable category was found,
        the category wording looks ambiguous,
        the language looks difficult,
        retrieval routes disagree

        will skip if:
        the message is only a short contextual answer,
        the top product already contains an exact preference phrase,
        deterministic retrieval appears sufficient
        """

        terms = tokenize(frame.raw_message, drop_stopwords=False)
        if len(terms) < self.config.semantic_min_escalation_terms:
            return self._record(False, "short_or_contextual")

        if not active.category_phrases:
            return self._record(True, "missing_category")

        if top_exact_preference_match:
            return self._record(False, "exact_top_product_evidence")

        if (
            _has_ambiguous_category_shape(frame.category_phrases)
            and assessment.top10_stability < self.config.semantic_ambiguous_category_stability
        ):
            return self._record(True, "ambiguous_category")

        if (
            should_call_semantic_parser(
                frame.raw_message,
                has_fallback_span=any(
                    update.source == "fallback" for update in frame.slot_updates
                ),
            )
            and assessment.top10_stability < self.config.semantic_low_stability_threshold
        ):
            return self._record(True, "difficult_language_low_stability")

        return self._record(False, "deterministic_retrieval_sufficient")

    def decide_before_retrieval(
        self,
        frame: IntentFrame,
        active: ActiveState,
    ) -> SemanticEscalationDecision:
        """Use semantics before state mutation when a turn has compound intent.

        Corrections, clearings, and additions can coexist in one natural message.
        Simple schema answers stay local, preserving the low-latency common path;
        retrieval-aware escalation remains available after candidate generation.
        """

        terms = tokenize(frame.raw_message, drop_stopwords=False)
        if len(terms) < self.config.semantic_min_escalation_terms:
            return self._record(False, "preflight_short_or_contextual")
        operations = {update.operation for update in frame.slot_updates}
        has_fallback = any(update.source == "fallback" for update in frame.slot_updates)
        has_compound_change = len(frame.slot_updates) >= 2 and (
            frame.override
            or frame.no_preference_attribute is not None
            or "exclude" in operations
            or "set_any" in operations
        )
        if has_compound_change:
            return self._record(True, "compound_state_change")
        if not active.category_phrases and not frame.category_phrases:
            return self._record(True, "preflight_missing_category")
        if has_fallback and should_call_semantic_parser(
            frame.raw_message,
            has_fallback_span=True,
        ):
            return self._record(True, "preflight_difficult_language")
        return self._record(False, "preflight_deterministic_sufficient")

    def record_outcome(self, *, applied: bool) -> None:
        """Record whether grounded semantic evidence changed active state."""

        with self._lock:
            self._counts["semantic_applied" if applied else "semantic_noop"] += 1

    def stats(self) -> dict[str, int]:
        """Return credential-free call-decision counters."""

        with self._lock:
            return dict(self._counts)

    def _record(self, should_call: bool, reason: str) -> SemanticEscalationDecision:
        with self._lock:
            self._counts["decisions"] += 1
            self._counts["calls" if should_call else "skips"] += 1
            self._counts[f"reason:{reason}"] += 1
        return SemanticEscalationDecision(should_call, reason)


def _has_ambiguous_category_shape(values: tuple[str, ...]) -> bool:
    for value in values:
        normalized = normalize_text(value)
        if normalized.startswith(("to ", "something ")):
            return True
    return False
