"""Inference with full traceability.

Every output row records the model version, preprocessing version, decision
rule and status. Rows that cannot be processed safely get ``status="rejected"``
and no predicted class; they are never silently given a default prediction.
Model scores are labelled as uncalibrated unless calibration has been
established and declared by the caller.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

import numpy as np
import pandas as pd

from ..preprocessing import Preprocessor

PREDICTION_COLUMNS = [
    "event_id",
    "predicted_class",
    "score",
    "score_kind",
    "threshold",
    "decision_rule",
    "model_version",
    "preprocessing_version",
    "inferred_at",
    "status",
    "error",
    "explanation_ref",
]


class InferenceError(RuntimeError):
    pass


class Predictor:
    def __init__(
        self,
        model: Any,
        model_version: str,
        preprocessor: Preprocessor,
        *,
        positive_class: Any = None,
        threshold: float | None = None,
        calibrated: bool = False,
    ):
        if threshold is not None:
            if positive_class is None:
                raise InferenceError("a threshold requires positive_class")
            if not hasattr(model, "predict_proba"):
                raise InferenceError("a threshold requires a model with predict_proba")
            if len(getattr(model, "classes_", [])) != 2:
                raise InferenceError("threshold decisions are only supported for binary models")
            if not 0.0 <= threshold <= 1.0:
                raise InferenceError("threshold must be within [0, 1]")
            if positive_class not in list(model.classes_):
                raise InferenceError(f"positive_class {positive_class!r} not in model classes {list(model.classes_)}")
        self.model = model
        self.model_version = model_version
        self.preprocessor = preprocessor
        self.positive_class = positive_class
        self.threshold = threshold
        self.calibrated = calibrated
        self._model_feature_order = self._check_feature_compatibility()

    def _check_feature_compatibility(self) -> list[str]:
        schema_names = self.preprocessor.schema.feature_names
        names_in = getattr(self.model, "feature_names_in_", None)
        if names_in is not None:
            names_in = [str(n) for n in names_in]
            if set(names_in) != set(schema_names) or len(names_in) != len(schema_names):
                raise InferenceError(
                    "model was trained on a different feature set than schema "
                    f"{self.preprocessor.schema.schema_id}: "
                    f"model-only={sorted(set(names_in) - set(schema_names))} "
                    f"schema-only={sorted(set(schema_names) - set(names_in))}"
                )
            return names_in  # same set: feed columns in the model's own order
        n_in = getattr(self.model, "n_features_in_", None)
        if n_in is not None and n_in != len(schema_names):
            raise InferenceError(
                f"model expects {n_in} features but schema defines {len(schema_names)}"
            )
        return schema_names

    @property
    def score_kind(self) -> str | None:
        if not hasattr(self.model, "predict_proba"):
            return None
        suffix = "calibrated" if self.calibrated else "uncalibrated"
        if self.threshold is not None:
            return f"positive_class_score_{suffix}"
        return f"max_class_score_{suffix}"

    @property
    def decision_rule(self) -> str:
        if self.threshold is not None:
            return f"score({self.positive_class}) >= {self.threshold}"
        return "model.predict()"

    def model_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        """The preprocessed rows exactly as the model receives them (columns in the model's order).

        Rows that preprocessing rejects are left out; explanations use this so they see the same input.
        """
        return self.preprocessor.transform(df).X[self._model_feature_order]

    def _model_input(self, X: pd.DataFrame) -> Any:
        X = X[self._model_feature_order]
        if getattr(self.model, "feature_names_in_", None) is not None:
            return X
        return X.to_numpy()

    def predict(self, df: pd.DataFrame, event_ids: Sequence[Any] | None = None) -> pd.DataFrame:
        if event_ids is None:
            event_ids = df.index.tolist()
        if len(event_ids) != len(df):
            raise InferenceError("event_ids length does not match input rows")
        now = datetime.now(timezone.utc).isoformat()
        out = pd.DataFrame(
            {
                "event_id": list(event_ids),
                "predicted_class": pd.Series([None] * len(df), dtype=object).values,
                "score": np.nan,
                "score_kind": self.score_kind,
                "threshold": self.threshold,
                "decision_rule": self.decision_rule,
                "model_version": self.model_version,
                "preprocessing_version": self.preprocessor.version_id,
                "inferred_at": now,
                "status": "ok",
                "error": None,
                "explanation_ref": None,
            },
            index=df.index,
        )[PREDICTION_COLUMNS]

        result = self.preprocessor.transform(df)
        if len(result.rejected_index):
            out.loc[result.rejected_index, "status"] = "rejected"
            out.loc[result.rejected_index, "error"] = "non-finite feature values after preprocessing"
        if len(result.X) == 0:
            return out.reset_index(drop=True)

        X_in = self._model_input(result.X)
        try:
            if self.threshold is not None:
                proba = self.model.predict_proba(X_in)
                classes = list(self.model.classes_)
                pos = classes.index(self.positive_class)
                neg_class = classes[1 - pos]
                score = proba[:, pos]
                pred = np.where(score >= self.threshold, self.positive_class, neg_class)
            else:
                pred = self.model.predict(X_in)
                score = (
                    self.model.predict_proba(X_in).max(axis=1)
                    if hasattr(self.model, "predict_proba")
                    else np.full(len(pred), np.nan)
                )
        except Exception as exc:  # surface model failures; never fabricate output
            raise InferenceError(f"model {self.model_version} failed during inference: {exc}") from exc

        out.loc[result.X.index, "predicted_class"] = pd.Series(pred, index=result.X.index).astype(object)
        out.loc[result.X.index, "score"] = score
        return out.reset_index(drop=True)
