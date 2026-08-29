"""StateReducer implementing deterministic, event-sourced state transitions."""

from __future__ import annotations

from shopping_copilot.dialog.models import (
    ActiveConstraint,
    ActiveState,
    CustomerProfile,
)
from shopping_copilot.understanding.models import (
    Attribute,
    IntentFrame,
    SlotUpdate,
)


class StateReducer:
    """Deterministic reducer applying parsed IntentFrames to ActiveState adhering to 9 state invariants."""

    @staticmethod
    def reduce(
        prior_state: ActiveState,
        intent_frame: IntentFrame,
        turn: int,
        user_profile: CustomerProfile | None = None,
    ) -> ActiveState:
        category = prior_state.category
        constraints = list(prior_state.constraints)
        exclusions = list(prior_state.exclusions)
        any_attributes = set(prior_state.any_attributes)

        is_override_turn = "override" in intent_frame.dialogue_acts

        # If override is detected without specific slot targets, clear earlier soft preferences
        if is_override_turn and not any(s.operation == "replace" for s in intent_frame.slot_updates):
            # Deactivate earlier soft constraints
            constraints = [c for c in constraints if c.strength == "hard"]

        for update in intent_frame.slot_updates:
            attr = update.attribute

            # ---------------------------------------------------------------
            # 1. Operation: set_any (indifference / no preference)
            # ---------------------------------------------------------------
            if update.operation == "set_any":
                # Clear active positive and negative constraints for this attribute
                constraints = [c for c in constraints if c.attribute != attr]
                exclusions = [e for e in exclusions if e.attribute != attr]
                any_attributes.add(attr)
                continue

            # If an explicit value is specified, remove from suppression set
            any_attributes.discard(attr)

            # ---------------------------------------------------------------
            # 2. Operation: exclude
            # ---------------------------------------------------------------
            if update.operation == "exclude":
                new_exclusion = ActiveConstraint(
                    attribute=attr,
                    relation=update.relation,
                    values=update.normalized_values,
                    alternative_group=update.alternative_group,
                    strength=update.strength,
                    confidence=update.confidence,
                    source_turn=turn,
                    raw_span=update.raw_span,
                )
                # Avoid duplicates
                if not any(
                    e.attribute == attr and e.values == update.normalized_values
                    for e in exclusions
                ):
                    exclusions.append(new_exclusion)
                # Also remove from positive constraints if present
                constraints = [
                    c for c in constraints
                    if not (c.attribute == attr and c.values == update.normalized_values)
                ]
                continue

            # ---------------------------------------------------------------
            # 3. Category Updates
            # ---------------------------------------------------------------
            if attr == Attribute.CATEGORY and update.normalized_values:
                new_cat = update.normalized_values[0]
                if category is not None and category != new_cat:
                    # Category changed: clear category-specific size/style constraints (Invariant 6)
                    constraints = [
                        c for c in constraints
                        if c.attribute not in (Attribute.SIZE, Attribute.STYLE)
                    ]
                category = new_cat
                continue

            # ---------------------------------------------------------------
            # 4. Operations: replace / set / add
            # ---------------------------------------------------------------
            new_constraint = ActiveConstraint(
                attribute=attr,
                relation=update.relation,
                values=update.normalized_values,
                alternative_group=update.alternative_group,
                strength=update.strength,
                confidence=update.confidence,
                source_turn=turn,
                raw_span=update.raw_span,
            )

            if update.operation in ("replace", "set"):
                # Invariant 2: Later explicit replacements deactivate earlier values for same slot
                # Invariant 8: Inferred evidence cannot replace explicit evidence
                existing_explicit = [
                    c for c in constraints
                    if c.attribute == attr and c.confidence >= 0.90
                ]
                if update.explicitness == "inferred" and existing_explicit:
                    # Do not replace explicit with inferred
                    continue

                constraints = [c for c in constraints if c.attribute != attr]
                constraints.append(new_constraint)

            elif update.operation == "add":
                # Invariant 3: Compatible additions remain active
                # Avoid exact duplicate constraints
                if not any(
                    c.attribute == attr and c.values == update.normalized_values
                    for c in constraints
                ):
                    constraints.append(new_constraint)

        # -------------------------------------------------------------------
        # Update Profile Preferences (Invariant 1 & 5)
        # -------------------------------------------------------------------
        profile_prefs: list[str] = []
        if user_profile and user_profile.preference_tags:
            for tag in user_profile.preference_tags:
                tag_lower = tag.lower()
                # Check if tag corresponds to an ANY/suppressed attribute
                if any(attr.value in tag_lower for attr in any_attributes):
                    continue
                # Check if tag conflicts with an explicit exclusion
                if any(
                    any(val in tag_lower for val in e.values)
                    for e in exclusions
                ):
                    continue
                profile_prefs.append(tag)

        # -------------------------------------------------------------------
        # Update Preserved Raw Phrases and Residual Product Terms
        # -------------------------------------------------------------------
        # Combine recent phrases, capping to avoid unbounded growth
        raw_phrases_list = list(prior_state.raw_phrases)
        for need in intent_frame.subjective_needs:
            if need and need not in raw_phrases_list:
                raw_phrases_list.append(need)

        # Residual product terms: current terms take precedence
        term_dict = {t: True for t in intent_frame.product_terms}
        for t in prior_state.residual_product_terms:
            term_dict[t] = True
        residual_terms = tuple(term_dict.keys())[:30]

        return ActiveState(
            category=category,
            constraints=tuple(constraints),
            exclusions=tuple(exclusions),
            any_attributes=frozenset(any_attributes),
            profile_preferences=tuple(profile_prefs),
            raw_phrases=tuple(raw_phrases_list[-10:]),
            residual_product_terms=residual_terms,
            turn=turn,
        )
