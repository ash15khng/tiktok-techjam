from __future__ import annotations

import unittest

from shopping_copilot.understanding.interpreter import MessageInterpreter
from shopping_copilot.understanding.models import Attribute


class MessageInterpreterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.interpreter = MessageInterpreter()

    def parse(self, message: str, last_ask: str | None = None):
        return self.interpreter.parse(message, last_ask_attribute=last_ask, context="")

    def test_browsing_message_keeps_category_without_boilerplate(self) -> None:
        frame = self.parse("I'm looking for running shoes, but I'm still exploring.")

        self.assertEqual(frame.category_phrases, ("running shoes",))
        self.assertEqual(frame.preference_phrases, ())

    def test_constraint_payload_preserves_raw_feature_text(self) -> None:
        frame = self.parse("For that, what matters is: waterproof upper; non-slip sole.")

        self.assertEqual(frame.preference_phrases, ("waterproof upper", "non-slip sole"))

    def test_override_is_a_replacement_event(self) -> None:
        frame = self.parse("Actually, ignore my earlier preference. What I need is: leather.")

        self.assertTrue(frame.override)
        self.assertEqual(frame.slot_updates[0].operation, "replace")
        self.assertEqual(frame.slot_updates[0].attribute, Attribute.MATERIAL)

    def test_boundary_reply_uses_last_asked_attribute(self) -> None:
        frame = self.parse("I don't have a preference; please use your judgment.", "color")

        self.assertEqual(frame.no_preference_attribute, Attribute.COLOR)


if __name__ == "__main__":
    unittest.main()
