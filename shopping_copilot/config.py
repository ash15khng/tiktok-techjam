"""Configuration parameters and frozen dataclasses for the Shopping Copilot."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class UnderstandingConfig:
    """Hyperparameters for message interpretation, entity linking, and rule matching."""

    fuzzy_min_score: float = 0.84
    fuzzy_min_margin: float = 0.08
    max_terms_for_lexical: int = 24
    budget_tolerance_ratio: float = 0.20  # "around $50" -> [40.0, 60.0]
    
    # Confidence calibration by provenance
    confidence_numeric_rule: float = 0.99
    confidence_catalog_exact: float = 0.97
    confidence_catalog_alias: float = 0.93
    confidence_contextual_reply: float = 0.90
    confidence_fuzzy_link: float = 0.85
    confidence_inferred: float = 0.70


@dataclass(frozen=True)
class NeedAssessorConfig:
    """Hyperparameters for assessing query specificity and routing focus score."""

    catalog_total_products: int = 50_000
    weight_category_specificity: float = 0.35
    weight_constraint_density: float = 0.25
    weight_numeric_specificity: float = 0.15
    weight_lexical_specificity: float = 0.15
    weight_parse_certainty: float = 0.10

    intercept_z: float = -0.25
    coef_specificity: float = 1.20
    coef_commitment: float = 0.80
    coef_exploration: float = 1.00
    coef_unresolved_need: float = 0.60

    exploring_exploration_threshold: float = 0.60
    deciding_specificity_threshold: float = 0.75
    deciding_commitment_threshold: float = 0.50


@dataclass(frozen=True)
class DialogConfig:
    """Hyperparameters for session state tracking and dialog transitions."""

    max_turns: int = 10
    profile_influence_cap: float = 0.05


@dataclass(frozen=True)
class CopilotConfig:
    """Master frozen configuration."""

    understanding: UnderstandingConfig = field(default_factory=UnderstandingConfig)
    need_assessor: NeedAssessorConfig = field(default_factory=NeedAssessorConfig)
    dialog: DialogConfig = field(default_factory=DialogConfig)


DEFAULT_CONFIG = CopilotConfig()

