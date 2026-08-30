"""Deterministic state transitions for accumulation, overrides, and Boundary."""

from __future__ import annotations

import re

from submission.src.catalog.attributes import (
    AttributeValueResolver,
    EmptyAttributeResolver,
)
from submission.src.dialog.models import SessionState
from submission.src.understanding.models import IntentFrame


BROAD_PREFERENCE_OVERRIDE_RE = re.compile(
    r"\b(?:ignore|forget)\s+(?:my\s+)?(?:earlier|previous)\s+preference\b",
    re.IGNORECASE,
)


def _append_unique(values: list[str], additions: tuple[str, ...]) -> None:
    for value in additions:
        if value and value not in values:
            values.append(value)


class StateReducer:
    """The only component allowed to mutate Active State."""

    def __init__(self, attribute_resolver: AttributeValueResolver | None = None) -> None:
        self.attribute_resolver = attribute_resolver or EmptyAttributeResolver()

    def apply(self, state: SessionState, frame: IntentFrame) -> SessionState:
        """Apply one deterministic Intent Frame and advance session turn state."""

        self._record_clarification_outcome(state, frame)
        active = state.active
        broad_preference_override = bool(BROAD_PREFERENCE_OVERRIDE_RE.search(frame.raw_message))
        if frame.override or any(update.operation == "set_any" for update in frame.slot_updates):
            active.search_rewrites.clear()
        if frame.override:
            state.intent_override_active = True
            # clears past recommendation
            state.recommendation_exposure.clear()
            if frame.category_phrases:
                # A true category override invalidates all old product evidence.
                active.preference_phrases.clear()
                active.exclusions.clear()
                active.slot_values.clear()
                active.suppressed_attributes.clear()
                active.asked_attributes.clear()
                state.clarification_outcomes.clear()
            elif broad_preference_override and active.preference_phrases:
                stale = active.preference_phrases.pop(0)
                for attribute, values in tuple(active.slot_values.items()):
                    active.slot_values[attribute] = [value for value in values if value != stale]
                    if not active.slot_values[attribute]:
                        active.slot_values.pop(attribute)
        if frame.category_phrases:
            if frame.override and any(
                update.attribute.value == "category" for update in frame.slot_updates
            ):
                active.category_phrases.clear()
            _append_unique(active.category_phrases, frame.category_phrases)

        _append_unique(
            active.preference_phrases,
            frame.preference_phrases,
        )
        if frame.query_rewrites:
            active.search_rewrites[:] = list(dict.fromkeys(frame.query_rewrites))
        _append_unique(active.exclusions, frame.exclusions)

        for update in frame.slot_updates:
            attribute = update.attribute.value
            if update.operation == "suppress":
                # Retain the disclosed phrase for retrieval, but remove the
                # typed slot so the decline cannot add budget/range scoring or
                # masquerade as a newly confirmed structured answer.
                active.slot_values.pop(attribute, None)
                active.suppressed_attributes.add(attribute)
                continue
            if attribute == "color" and update.operation == "replace":
                self._remove_embedded_colors(active.category_phrases)
            if update.operation == "set_any":
                # "I don't care about color" clears color and suppresses repeats.
                stale_values = active.slot_values.pop(attribute, [])
                active.preference_phrases[:] = [
                    value for value in active.preference_phrases if value not in stale_values
                ]
                active.suppressed_attributes.add(attribute)
                continue
            if update.operation == "exclude":
                continue
            if update.operation == "replace":
                stale_values = active.slot_values.get(attribute, [])
                if not broad_preference_override:
                    active.preference_phrases[:] = [
                        value for value in active.preference_phrases if value not in stale_values
                    ]
                active.slot_values[attribute] = [update.value]
            else:
                values = active.slot_values.setdefault(attribute, [])
                if update.value not in values:
                    values.append(update.value)
            active.suppressed_attributes.discard(attribute)
        state.turn_count += 1
        state.last_feedback_negative = frame.negative_feedback
        return state

    def _remove_embedded_colors(self, categories: list[str]) -> None:
        """Remove stale color adjectives only when color is explicitly replaced."""

        revised: list[str] = []
        for category in categories:
            value = category
            if len(category.split()) <= 2:
                for attribute, phrase in self.attribute_resolver.matched_values(category):
                    if attribute != "color":
                        continue
                    value = re.sub(
                        rf"\b{re.escape(phrase)}\b",
                        " ",
                        value,
                        flags=re.IGNORECASE,
                    )
            cleaned = " ".join(value.split()).strip(" -;,.")
            revised.append(cleaned or category)
        categories[:] = list(dict.fromkeys(revised))

    @staticmethod
    def _record_clarification_outcome(state: SessionState, frame: IntentFrame) -> None:
        attribute = state.last_ask_attribute
        if not attribute or attribute == "other" or attribute in state.clarification_outcomes:
            return
        updates = tuple(
            update
            for update in frame.slot_updates
            if update.attribute.value == attribute
        )
        if any(update.operation in {"set_any", "suppress"} for update in updates):
            state.clarification_outcomes[attribute] = "declined"
        elif any(update.operation in {"add", "replace"} and update.value for update in updates):
            state.clarification_outcomes[attribute] = "answered"
        elif frame.slot_updates or frame.category_phrases or frame.preference_phrases:
            state.clarification_outcomes[attribute] = "redirected"

    def apply_semantic(self, state: SessionState, frame: IntentFrame) -> bool:
        """Apply grounded semantic operations without advancing the turn."""

        active = state.active
        previous_rewrites = tuple(active.search_rewrites)
        if frame.query_rewrites:
            active.search_rewrites[:] = list(dict.fromkeys(frame.query_rewrites))
        changed = previous_rewrites != tuple(active.search_rewrites)
        for update in frame.slot_updates:
            if update.source != "semantic":
                continue
            attribute = update.attribute.value
            if update.operation == "set_any":
                stale_values = active.slot_values.pop(attribute, [])
                active.preference_phrases[:] = [
                    value for value in active.preference_phrases if value not in stale_values
                ]
                changed = (
                    changed
                    or bool(stale_values)
                    or attribute not in active.suppressed_attributes
                )
                active.suppressed_attributes.add(attribute)
                continue
            if update.operation == "exclude":
                before = len(active.exclusions)
                _append_unique(active.exclusions, (update.value,))
                changed = changed or len(active.exclusions) != before
                continue
            if attribute == "category":
                if update.operation == "replace":
                    changed = changed or active.category_phrases != [update.value]
                    active.category_phrases[:] = [update.value]
                else:
                    before = len(active.category_phrases)
                    _append_unique(active.category_phrases, (update.value,))
                    changed = changed or len(active.category_phrases) != before
            else:
                if update.operation == "replace":
                    stale_values = active.slot_values.get(attribute, [])
                    active.preference_phrases[:] = [
                        value for value in active.preference_phrases if value not in stale_values
                    ]
                before_preferences = len(active.preference_phrases)
                _append_unique(active.preference_phrases, (update.value,))
                changed = changed or len(active.preference_phrases) != before_preferences
            if update.operation == "replace":
                previous = active.slot_values.get(attribute)
                active.slot_values[attribute] = [update.value]
                changed = changed or previous != [update.value]
            else:
                values = active.slot_values.setdefault(attribute, [])
                if update.value not in values:
                    values.append(update.value)
                    changed = True
            active.suppressed_attributes.discard(attribute)
        return changed
