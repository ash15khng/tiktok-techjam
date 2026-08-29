"""Deterministic state transitions for accumulation, overrides, and Boundary."""

from __future__ import annotations

from shopping_copilot.dialog.models import SessionState
from shopping_copilot.understanding.models import IntentFrame


def _append_unique(values: list[str], additions: tuple[str, ...]) -> None:
    for value in additions:
        if value and value not in values:
            values.append(value)


class StateReducer:
    """The only component allowed to mutate Active State."""

    def apply(self, state: SessionState, frame: IntentFrame) -> SessionState:
        active = state.active
        if frame.override:
            # A changed intent invalidates the meaning of earlier rejection:
            # previously shown items may become relevant under the new request.
            state.recommendation_exposure.clear()
            if frame.category_phrases:
                active.preference_phrases.clear()
                active.exclusions.clear()
                active.slot_values.clear()
            elif active.preference_phrases:
                # The simulator and ordinary corrections refer to the earlier
                # preference in the opening request. Later confirmed evidence
                # remains active unless the category itself changes.
                stale = active.preference_phrases.pop(0)
                for attribute, values in tuple(active.slot_values.items()):
                    active.slot_values[attribute] = [value for value in values if value != stale]
                    if not active.slot_values[attribute]:
                        active.slot_values.pop(attribute)
        if frame.category_phrases:
            if frame.override and any(update.attribute.value == "category" for update in frame.slot_updates):
                active.category_phrases.clear()
            _append_unique(active.category_phrases, frame.category_phrases)
        _append_unique(active.preference_phrases, (*frame.preference_phrases, *frame.query_rewrites))
        _append_unique(active.exclusions, frame.exclusions)
        for update in frame.slot_updates:
            attribute = update.attribute.value
            if update.operation == "set_any":
                active.slot_values.pop(attribute, None)
                active.suppressed_attributes.add(attribute)
                continue
            if update.operation == "exclude":
                continue
            if update.operation == "replace":
                active.slot_values[attribute] = [update.value]
            else:
                values = active.slot_values.setdefault(attribute, [])
                if update.value not in values:
                    values.append(update.value)
            active.suppressed_attributes.discard(attribute)
        state.turn_count += 1
        state.last_feedback_negative = frame.negative_feedback
        return state
