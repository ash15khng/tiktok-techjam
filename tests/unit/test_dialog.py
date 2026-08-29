"""Unit tests for the dialog subsystem: state reduction invariants and session store."""

from __future__ import annotations

import unittest

from shopping_copilot.dialog.models import (
    ActiveConstraint,
    ActiveState,
    CustomerProfile,
    TurnRecord,
)
from shopping_copilot.dialog.reducer import StateReducer
from shopping_copilot.dialog.store import SessionStore
from shopping_copilot.understanding.models import (
    Attribute,
    IntentFrame,
    Relation,
    SlotUpdate,
)


class TestStateReducerInvariants(unittest.TestCase):
    def test_invariant_2_replacement_deactivates_earlier_slot(self) -> None:
        """Later explicit replacement deactivates previous value for the same slot."""
        prior = ActiveState(
            constraints=(
                ActiveConstraint(
                    attribute=Attribute.COLOR,
                    relation=Relation.EQ,
                    values=("black",),
                    strength="hard",
                    source_turn=1,
                ),
            ),
            turn=1,
        )
        frame = IntentFrame(
            dialogue_acts=("override",),
            slot_updates=(
                SlotUpdate(
                    attribute=Attribute.COLOR,
                    operation="replace",
                    relation=Relation.EQ,
                    normalized_values=("white",),
                    strength="hard",
                    confidence=0.98,
                    source_turn=2,
                ),
            ),
            product_terms=("white",),
        )
        next_state = StateReducer.reduce(prior, frame, turn=2)
        color_constraints = next_state.get_constraints(Attribute.COLOR)
        self.assertEqual(len(color_constraints), 1)
        self.assertEqual(color_constraints[0].values, ("white",))

    def test_invariant_3_compatible_additions_remain_active(self) -> None:
        """Compatible additions for different slots accumulate."""
        prior = ActiveState(
            constraints=(
                ActiveConstraint(
                    attribute=Attribute.COLOR,
                    relation=Relation.EQ,
                    values=("blue",),
                    source_turn=1,
                ),
            ),
            turn=1,
        )
        frame = IntentFrame(
            dialogue_acts=("inform",),
            slot_updates=(
                SlotUpdate(
                    attribute=Attribute.MATERIAL,
                    operation="add",
                    relation=Relation.EQ,
                    normalized_values=("mesh",),
                    source_turn=2,
                ),
            ),
            product_terms=("mesh",),
        )
        next_state = StateReducer.reduce(prior, frame, turn=2)
        self.assertEqual(len(next_state.constraints), 2)
        self.assertEqual(next_state.get_constraints(Attribute.MATERIAL)[0].values, ("mesh",))

    def test_invariant_4_exclusions_stored_separately(self) -> None:
        """Exclusions are kept in exclusions tuple and removed from positive constraints."""
        prior = ActiveState(
            constraints=(
                ActiveConstraint(
                    attribute=Attribute.COLOR,
                    relation=Relation.EQ,
                    values=("black",),
                    source_turn=1,
                ),
            ),
            turn=1,
        )
        frame = IntentFrame(
            dialogue_acts=("inform",),
            slot_updates=(
                SlotUpdate(
                    attribute=Attribute.COLOR,
                    operation="exclude",
                    relation=Relation.NEQ,
                    normalized_values=("black",),
                    source_turn=2,
                ),
            ),
            product_terms=(),
        )
        next_state = StateReducer.reduce(prior, frame, turn=2)
        self.assertEqual(len(next_state.get_constraints(Attribute.COLOR)), 0)
        self.assertEqual(len(next_state.get_exclusions(Attribute.COLOR)), 1)
        self.assertEqual(next_state.get_exclusions(Attribute.COLOR)[0].values, ("black",))

    def test_invariant_5_set_any_clears_slot_and_suppresses_profile(self) -> None:
        """set_any clears active slot, adds to any_attributes, and suppresses profile tag."""
        profile = CustomerProfile(preference_tags=("color: red", "fit: slim"))
        prior = ActiveState(
            constraints=(
                ActiveConstraint(
                    attribute=Attribute.COLOR,
                    relation=Relation.EQ,
                    values=("red",),
                    source_turn=1,
                ),
            ),
            turn=1,
        )
        frame = IntentFrame(
            dialogue_acts=("indifference",),
            slot_updates=(
                SlotUpdate(
                    attribute=Attribute.COLOR,
                    operation="set_any",
                    relation=Relation.EQ,
                    normalized_values=(),
                    source_turn=2,
                ),
            ),
            product_terms=(),
        )
        next_state = StateReducer.reduce(prior, frame, turn=2, user_profile=profile)
        self.assertTrue(next_state.is_suppressed(Attribute.COLOR))
        self.assertEqual(len(next_state.get_constraints(Attribute.COLOR)), 0)
        # Profile tag with "color" should be filtered out
        self.assertNotIn("color: red", next_state.profile_preferences)
        self.assertIn("fit: slim", next_state.profile_preferences)

    def test_invariant_6_category_change_resets_dependent_slots(self) -> None:
        """Category replacement clears category-specific size/style constraints."""
        prior = ActiveState(
            category="shoes",
            constraints=(
                ActiveConstraint(
                    attribute=Attribute.SIZE,
                    relation=Relation.EQ,
                    values=("10 wide",),
                    source_turn=1,
                ),
                ActiveConstraint(
                    attribute=Attribute.MATERIAL,
                    relation=Relation.EQ,
                    values=("leather",),
                    source_turn=1,
                ),
            ),
            turn=1,
        )
        frame = IntentFrame(
            dialogue_acts=("override",),
            slot_updates=(
                SlotUpdate(
                    attribute=Attribute.CATEGORY,
                    operation="set",
                    relation=Relation.EQ,
                    normalized_values=("jackets",),
                    source_turn=2,
                ),
            ),
            product_terms=("jackets",),
        )
        next_state = StateReducer.reduce(prior, frame, turn=2)
        self.assertEqual(next_state.category, "jackets")
        # Size should be cleared, material preserved
        self.assertEqual(len(next_state.get_constraints(Attribute.SIZE)), 0)
        self.assertEqual(len(next_state.get_constraints(Attribute.MATERIAL)), 1)


class TestSessionStore(unittest.TestCase):
    def setUp(self) -> None:
        self.store = SessionStore()

    def test_session_lifecycle(self) -> None:
        session_id = "test_sess_001"
        profile_dict = {
            "summary": "Likes leather and fit",
            "preference_tags": ["leather", "fit"],
            "average_prior_rating": 4.5,
        }
        state = self.store.reset(session_id, profile_dict)
        self.assertEqual(state.session_id, session_id)
        self.assertTrue(self.store.has_session(session_id))
        self.assertEqual(state.user_profile.average_prior_rating, 4.5)

        context = self.store.get_dialogue_context(session_id, turn=1)
        self.assertEqual(context.turn, 1)

        # Record a turn
        turn_rec = TurnRecord(
            turn=1,
            user_message="Hello",
            intent_frame=IntentFrame(dialogue_acts=("inform",), slot_updates=(), product_terms=()),
        )
        self.store.record_turn(session_id, turn_rec, ask_attribute=Attribute.MATERIAL, recommendations=("A", "B"))
        sess_after = self.store.get_session(session_id)
        self.assertEqual(len(sess_after.turn_history), 1)
        self.assertEqual(sess_after.last_ask_attribute, Attribute.MATERIAL)
        self.assertEqual(sess_after.last_recommendations, ("A", "B"))


if __name__ == "__main__":
    unittest.main()
