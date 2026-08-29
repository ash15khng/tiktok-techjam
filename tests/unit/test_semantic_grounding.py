from __future__ import annotations

import unittest

from shopping_copilot.contracts import SemanticInterpretation, SemanticSlotHypothesis
from shopping_copilot.understanding.models import Attribute, SlotUpdate
from shopping_copilot.understanding.semantic_grounding import ground_semantic_interpretation


class SemanticGroundingTest(unittest.TestCase):
    def test_keeps_anchored_rewrites_and_soft_evidence_but_rejects_unsafe_hints(self) -> None:
        semantic = SemanticInterpretation(
            query_rewrites=(
                "breathable formal wedding shoes",
                "waterproof boots",
                "avoid leather wedding shoes",
                "B012345678 wedding shoes",
            ),
            subjective_needs=("comfortable in humid weather", "unrelated snow gear"),
            slot_hypotheses=(
                SemanticSlotHypothesis("use_case", "outdoor wedding", 0.70, "humid outdoor wedding"),
                SemanticSlotHypothesis("feature", "waterproof", 0.70, "snow"),
                SemanticSlotHypothesis("material", "leather", 0.70, "comfortable"),
                SemanticSlotHypothesis("style", "formal", 0.40, "polished"),
            ),
        )

        grounded = ground_semantic_interpretation(
            semantic,
            raw_message="Something polished but comfortable for a humid outdoor wedding.",
            context="category=shoes",
            deterministic_updates=(),
            override=False,
            min_confidence=0.55,
            max_rewrite_terms=12,
        )

        self.assertEqual(grounded.query_rewrites, ("breathable formal wedding shoes",))
        self.assertEqual(grounded.subjective_needs, ("comfortable in humid weather",))
        self.assertEqual(grounded.preference_phrases, ("outdoor wedding",))
        self.assertEqual(len(grounded.slot_updates), 1)
        self.assertEqual(grounded.slot_updates[0].attribute, Attribute.USE_CASE)
        self.assertEqual(grounded.slot_updates[0].source, "semantic")

    def test_deterministic_attribute_wins_and_override_cannot_reuse_stale_context(self) -> None:
        semantic = SemanticInterpretation(
            query_rewrites=("formal wedding shoes",),
            slot_hypotheses=(SemanticSlotHypothesis("style", "formal", 0.70, "polished"),),
        )

        grounded = ground_semantic_interpretation(
            semantic,
            raw_message="Actually, make it polished.",
            context="category=shoes; preferences=wedding",
            deterministic_updates=(SlotUpdate(Attribute.STYLE, "replace", "polished", "polished"),),
            override=True,
            min_confidence=0.55,
            max_rewrite_terms=12,
        )

        self.assertEqual(grounded.query_rewrites, ())
        self.assertEqual(grounded.slot_updates, ())


if __name__ == "__main__":
    unittest.main()
