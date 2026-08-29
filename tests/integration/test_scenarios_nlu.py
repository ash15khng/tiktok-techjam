"""Integration tests for NLU and Dialog tracking across all four competition scenarios."""

from __future__ import annotations

import unittest

from shopping_copilot.dialog.models import CustomerProfile, TurnRecord
from shopping_copilot.dialog.reducer import StateReducer
from shopping_copilot.dialog.store import SessionStore
from shopping_copilot.understanding.assessment import NeedAssessor
from shopping_copilot.understanding.interpreter import MessageInterpreter
from shopping_copilot.understanding.models import Attribute, Relation


class TestCompetitionScenariosNLU(unittest.TestCase):
    def setUp(self) -> None:
        self.interpreter = MessageInterpreter()
        self.assessor = NeedAssessor()
        self.store = SessionStore()

    def test_scenario_buying(self) -> None:
        """Buying scenario: Turn 1 provides hard constraints; focus score is immediately high."""
        session_id = "test_buying_001"
        profile = {"summary": "Frequent buyer", "preference_tags": ["comfort"]}
        self.store.reset(session_id, profile)

        turn1_msg = "I'm looking for running shoes. A key requirement is: 100% cotton; budget under $50."
        context = self.store.get_dialogue_context(session_id, turn=1)
        frame1 = self.interpreter.parse(turn1_msg, context=context)

        # Apply state reducer
        session = self.store.get_session(session_id)
        active_state1 = StateReducer.reduce(session.active_state, frame1, turn=1, user_profile=session.user_profile)
        self.store.update_active_state(session_id, active_state1)

        # Assertions on ActiveState
        self.assertEqual(active_state1.category, "running shoes")
        materials = active_state1.get_constraints(Attribute.MATERIAL)
        self.assertEqual(len(materials), 1)
        self.assertEqual(materials[0].values, ("cotton",))

        budgets = active_state1.get_constraints(Attribute.BUDGET)
        self.assertEqual(len(budgets), 1)
        self.assertEqual(budgets[0].relation, Relation.LTE)
        self.assertEqual(budgets[0].values, ("50.0",))

        # Assess Need
        assessment = self.assessor.assess(active_state1, frame1)
        self.assertGreater(assessment.focus_score, 0.60)
        self.assertIn(assessment.decision_stage, ("narrowing", "deciding"))

    def test_scenario_browsing(self) -> None:
        """Browsing scenario: Turn 1 is exploratory; Turn 2 refines with clarification reply."""
        session_id = "test_browsing_001"
        self.store.reset(session_id, {})

        turn1_msg = "I'm looking for winter coats, but I'm still exploring."
        context1 = self.store.get_dialogue_context(session_id, turn=1)
        frame1 = self.interpreter.parse(turn1_msg, context=context1)

        session = self.store.get_session(session_id)
        active_state1 = StateReducer.reduce(session.active_state, frame1, turn=1, user_profile=session.user_profile)
        self.store.update_active_state(session_id, active_state1)

        assessment1 = self.assessor.assess(active_state1, frame1)
        self.assertEqual(assessment1.decision_stage, "exploring")
        self.assertGreaterEqual(assessment1.exploration, 0.60)

        # Agent asks about material
        self.store.record_turn(
            session_id,
            TurnRecord(turn=1, user_message=turn1_msg, intent_frame=frame1),
            ask_attribute=Attribute.MATERIAL,
        )

        # Turn 2: Customer reply
        turn2_msg = "For that, what matters is: wool."
        context2 = self.store.get_dialogue_context(session_id, turn=2)
        frame2 = self.interpreter.parse(turn2_msg, context=context2)

        session2 = self.store.get_session(session_id)
        active_state2 = StateReducer.reduce(session2.active_state, frame2, turn=2, user_profile=session2.user_profile)
        self.store.update_active_state(session_id, active_state2)

        materials = active_state2.get_constraints(Attribute.MATERIAL)
        self.assertEqual(len(materials), 1)
        self.assertEqual(materials[0].values, ("wool",))

    def test_scenario_intent_override(self) -> None:
        """Intent Override scenario: User changes mind; stale preference is completely deactivated."""
        session_id = "test_override_001"
        self.store.reset(session_id, {})

        # Turn 1: Initial preference for polyester
        turn1_msg = "I'm looking for jackets. I prefer polyester fabric."
        context1 = self.store.get_dialogue_context(session_id, turn=1)
        frame1 = self.interpreter.parse(turn1_msg, context=context1)
        sess = self.store.get_session(session_id)
        state1 = StateReducer.reduce(sess.active_state, frame1, turn=1)
        self.store.update_active_state(session_id, state1)
        self.assertEqual(state1.get_constraints(Attribute.MATERIAL)[0].values, ("polyester",))

        # Turn 2: Override message
        turn2_msg = "Actually, ignore my earlier preference. What I need is: 100% genuine leather."
        context2 = self.store.get_dialogue_context(session_id, turn=2)
        frame2 = self.interpreter.parse(turn2_msg, context=context2)
        sess = self.store.get_session(session_id)
        state2 = StateReducer.reduce(sess.active_state, frame2, turn=2)
        self.store.update_active_state(session_id, state2)

        # Polyester must be deactivated; leather must be active
        active_materials = state2.get_constraints(Attribute.MATERIAL)
        self.assertEqual(len(active_materials), 1)
        self.assertEqual(active_materials[0].values, ("leather",))

    def test_scenario_boundary(self) -> None:
        """Boundary scenario: User states no preference; attribute is suppressed and marked ANY."""
        session_id = "test_boundary_001"
        profile = CustomerProfile(preference_tags=("color: black",))
        self.store.reset(session_id, profile)

        # Turn 1: Boot search
        turn1_msg = "I'm looking for boots."
        context1 = self.store.get_dialogue_context(session_id, turn=1)
        frame1 = self.interpreter.parse(turn1_msg, context=context1)
        sess = self.store.get_session(session_id)
        state1 = StateReducer.reduce(sess.active_state, frame1, turn=1, user_profile=sess.user_profile)
        self.store.update_active_state(session_id, state1)

        # Agent asks about color
        self.store.record_turn(
            session_id,
            TurnRecord(turn=1, user_message=turn1_msg, intent_frame=frame1),
            ask_attribute=Attribute.COLOR,
        )

        # Turn 2: User says no preference on color
        turn2_msg = "I don't have a preference for color; please use your judgment."
        context2 = self.store.get_dialogue_context(session_id, turn=2)
        frame2 = self.interpreter.parse(turn2_msg, context=context2)
        sess = self.store.get_session(session_id)
        state2 = StateReducer.reduce(sess.active_state, frame2, turn=2, user_profile=sess.user_profile)
        self.store.update_active_state(session_id, state2)

        # Color must be marked ANY / suppressed
        self.assertTrue(state2.is_suppressed(Attribute.COLOR))
        self.assertEqual(len(state2.get_constraints(Attribute.COLOR)), 0)
        # Profile preference for color must also be suppressed
        self.assertNotIn("color: black", state2.profile_preferences)


if __name__ == "__main__":
    unittest.main()

