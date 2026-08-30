from __future__ import annotations

import unittest

from submission.src.contracts import SemanticInterpretation, SemanticSlotHypothesis
from submission.src.understanding.models import Attribute, SlotUpdate
from submission.src.understanding.semantic_grounding import ground_semantic_interpretation


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
                SemanticSlotHypothesis(
                    "use_case",
                    "outdoor wedding",
                    0.70,
                    "humid outdoor wedding",
                ),
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

    def test_live_probe_shape_retains_rewrites_but_rejects_unsupported_inferences(self) -> None:
        semantic = SemanticInterpretation(
            query_rewrites=("polished shoes", "outdoor wedding shoes"),
            subjective_needs=("comfortable", "humidity resistant"),
            slot_hypotheses=(
                SemanticSlotHypothesis("category", "wedding shoes", 0.70, "humid outdoor wedding"),
                SemanticSlotHypothesis(
                    "material",
                    "breathable material",
                    0.70,
                    "humid outdoor wedding",
                ),
                SemanticSlotHypothesis("color", "neutral color", 0.60, "polished shoes"),
            ),
        )

        grounded = ground_semantic_interpretation(
            semantic,
            raw_message="I need comfortable, polished shoes for a humid outdoor wedding.",
            context="category=shoes",
            deterministic_updates=(),
            override=False,
            min_confidence=0.55,
            max_rewrite_terms=12,
        )

        self.assertEqual(grounded.query_rewrites, ("polished shoes", "outdoor wedding shoes"))
        self.assertEqual(grounded.subjective_needs, ("comfortable",))
        self.assertEqual(grounded.slot_updates, ())


if __name__ == "__main__":
    unittest.main()
