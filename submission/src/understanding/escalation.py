"""Retrieval-aware decision boundary for optional semantic interpretation."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from threading import RLock

from submission.src.catalog.normalization import normalize_text, tokenize
from submission.src.config import MVPConfig
from submission.src.dialog.models import ActiveState
from submission.src.retrieval.models import RetrievalAssessment
from submission.src.understanding.models import IntentFrame
from submission.src.understanding.semantic import should_call_semantic_parser


@dataclass(frozen=True)
class SemanticEscalationDecision:
    should_call: bool
    reason: str


class SemanticEscalationPolicy:
    """Call semantics only when language and deterministic evidence warrant it."""

    def __init__(self, config: MVPConfig) -> None:
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

    def record_outcome(self, *, applied: bool) -> None:
        with self._lock:
            self._counts["semantic_applied" if applied else "semantic_noop"] += 1

    def stats(self) -> dict[str, int]:
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
