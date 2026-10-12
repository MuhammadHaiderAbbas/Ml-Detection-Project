"""Exact SHAP attributions for tree-based scikit-learn classifiers.

Uses SHAP's TreeExplainer (the polynomial-time exact algorithm, path-dependent
feature perturbation), so no background sample and no sampling error is
involved. Every explanation is checked before it is returned: the base value
plus the sum of the contributions must reproduce the model's own output for
that row (``predict_proba`` or ``decision_function``) to within
:data:`ADDITIVITY_TOLERANCE`. If it does not, an :class:`ExplanationError` is
raised; an explanation that does not add up to the model output is never shown.

Attributions are computed on the model's input, after preprocessing. The
platform's preprocessing is per feature (imputation, optional scaling), so each
model input corresponds to exactly one schema feature.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Sequence

import numpy as np
import pandas as pd

ADDITIVITY_TOLERANCE = 1e-6
METHOD = "shap.TreeExplainer (exact, tree_path_dependent)"

_PROBABILITY_MODELS = ("RandomForestClassifier", "ExtraTreesClassifier", "DecisionTreeClassifier")
_LOGIT_MODELS = ("HistGradientBoostingClassifier",)

_COMMON_LIMITS = [
    "SHAP values describe how this model produced its score for this event. They do not show that the "
    "event is an attack, and they do not identify a cause in the network.",
    "Attributions use the tree-path-dependent method: they reflect the training data as captured in the "
    "trees. Correlated features can share or swap credit.",
    "Values are computed on the model input after preprocessing (imputation and any scaling); the raw "
    "imported value is shown alongside.",
]


class ExplanationError(RuntimeError):
    """The model can't be explained, or the explanation failed its additivity check."""


@dataclass
class FeatureContribution:
    feature: str
    model_input: float
    contribution: float


@dataclass
class PredictionExplanation:
    method: str
    library: str
    output_space: str  # probability | log_odds | class_logit
    target_class: str
    base_value: float
    model_output: float
    additivity_error: float
    contributions: list[FeatureContribution]
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def supports(model: Any) -> tuple[bool, str]:
    """Whether this module can explain ``model`` exactly, and why not if it can't."""
    name = type(model).__name__
    if name in _PROBABILITY_MODELS + _LOGIT_MODELS and type(model).__module__.startswith("sklearn."):
        return True, f"{name} is explained exactly with SHAP TreeExplainer"
    return False, (f"{name} is not supported. Exact SHAP explanations are available for scikit-learn "
                   f"tree models ({', '.join(_PROBABILITY_MODELS + _LOGIT_MODELS)}); no approximate "
                   "explanation is substituted.")


def _shap() -> Any:
    try:
        import shap  # noqa: PLC0415  (heavy import, only when an explanation is requested)
    except ImportError as exc:  # pragma: no cover - shap is a pinned dependency
        raise ExplanationError("the shap package is not installed") from exc
    return shap


def explain_rows(model: Any, X: pd.DataFrame, target_classes: Sequence[Any]) -> list[PredictionExplanation]:
    """Explain each row of ``X`` (the exact model input) for the class given in ``target_classes``."""
    ok, why = supports(model)
    if not ok:
        raise ExplanationError(why)
    if len(target_classes) != len(X):
        raise ExplanationError("one target class is needed per row")
    shap = _shap()
    classes = [str(c) for c in model.classes_]
    targets = [str(t) for t in target_classes]
    for t in targets:
        if t not in classes:
            raise ExplanationError(f"class {t!r} is not one of the model's classes {classes}")

    model_input: Any = X if getattr(model, "feature_names_in_", None) is not None else X.to_numpy()
    try:
        explainer = shap.TreeExplainer(model)
        values = explainer.shap_values(X.to_numpy(dtype="float64"), check_additivity=False)
    except Exception as exc:  # the library failing must not turn into a fabricated answer
        raise ExplanationError(f"SHAP failed for {type(model).__name__}: {exc}") from exc
    base = np.atleast_1d(np.asarray(explainer.expected_value, dtype="float64"))
    if isinstance(values, list):  # older SHAP: one array per class
        values = np.stack(values, axis=-1)
    values = np.asarray(values, dtype="float64")

    name = type(model).__name__
    if name in _PROBABILITY_MODELS:
        space = "probability"
        output = np.asarray(model.predict_proba(model_input), dtype="float64")
        limits = ["Contributions are in units of the model's (uncalibrated) class score, between 0 and 1."]
    else:
        raw = np.asarray(model.decision_function(model_input), dtype="float64")
        if raw.ndim == 1:  # binary: one log-odds output for classes_[1]
            space = "log_odds"
            output = np.stack([-raw, raw], axis=1)
            values = np.stack([-values, values], axis=-1)
            base = np.array([-base[0], base[0]])
            limits = ["Contributions are in log-odds of the target class; the shown score is a probability "
                      "derived from them, so the two scales differ."]
        else:
            space = "class_logit"
            output = raw
            limits = ["Contributions are in the model's raw per-class score (before softmax); the shown "
                      "score is a probability derived from all classes' raw scores."]
    if values.ndim != 3 or values.shape[2] != len(classes) or values.shape[1] != X.shape[1]:
        raise ExplanationError(f"unexpected SHAP output shape {values.shape} for {len(classes)} classes")

    out: list[PredictionExplanation] = []
    features = [str(c) for c in X.columns]
    for i, t in enumerate(targets):
        k = classes.index(t)
        contrib = values[i, :, k]
        recon = float(base[k] + contrib.sum())
        err = abs(recon - float(output[i, k]))
        if not np.isfinite(err) or err > ADDITIVITY_TOLERANCE:
            raise ExplanationError(
                f"explanation does not reproduce the model output (difference {err:.3g}); refusing to show it")
        items = [FeatureContribution(f, float(v), float(c)) for f, v, c in zip(features, X.iloc[i].to_numpy(), contrib)]
        items.sort(key=lambda c: (-abs(c.contribution), c.feature))
        out.append(PredictionExplanation(
            method=METHOD, library=f"shap {shap.__version__}", output_space=space, target_class=t,
            base_value=float(base[k]), model_output=float(output[i, k]), additivity_error=err,
            contributions=items, limitations=limits + _COMMON_LIMITS,
        ))
    return out
