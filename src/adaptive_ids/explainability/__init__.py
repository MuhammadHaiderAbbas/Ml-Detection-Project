"""Model explanations (SHAP) that correspond exactly to the deployed model and preprocessing."""

from .tree_shap import (
    ADDITIVITY_TOLERANCE,
    ExplanationError,
    FeatureContribution,
    PredictionExplanation,
    explain_rows,
    supports,
)

__all__ = [
    "ADDITIVITY_TOLERANCE",
    "ExplanationError",
    "FeatureContribution",
    "PredictionExplanation",
    "explain_rows",
    "supports",
]
