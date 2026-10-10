"""The single preprocessing interface shared by training, evaluation and inference.

Design rules (see the specification, section 8):

* Feature order always follows the schema.
* Fitted statistics (imputation medians, scaling parameters) are learned in
  :meth:`Preprocessor.fit` on training data only and are frozen afterwards;
  :meth:`transform` never refits.
* Scaling and imputation are *off by default*. They are only applied when an
  experiment configuration explicitly asks for them, so that the original
  dissertation method can be reproduced unchanged (if the original model is a
  scikit-learn ``Pipeline`` it already contains its own transformations).
* Fitted state is persisted as JSON, never as a pickle.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..provenance import sha256_json
from ..schema import FeatureSchema

IMPUTATION_METHODS = ("none", "median", "zero")
SCALING_METHODS = ("none", "standard", "minmax")


class PreprocessingError(ValueError):
    """Input cannot be processed safely."""


@dataclass(frozen=True)
class PreprocessingConfig:
    imputation: str = "none"
    scaling: str = "none"
    version: str = "1.0.0"

    def __post_init__(self) -> None:
        if self.imputation not in IMPUTATION_METHODS:
            raise PreprocessingError(f"imputation must be one of {IMPUTATION_METHODS}")
        if self.scaling not in SCALING_METHODS:
            raise PreprocessingError(f"scaling must be one of {SCALING_METHODS}")


@dataclass
class TransformOutput:
    X: pd.DataFrame
    """Rows that were processed successfully, in schema feature order."""
    rejected_index: pd.Index
    """Index labels of input rows that could not be processed (still NaN/inf)."""


class Preprocessor:
    def __init__(self, schema: FeatureSchema, config: PreprocessingConfig | None = None):
        self.schema = schema
        self.config = config or PreprocessingConfig()
        self._state: dict[str, Any] | None = None

    # -- identity -----------------------------------------------------------

    @property
    def is_fitted(self) -> bool:
        return self._state is not None

    @property
    def version_id(self) -> str:
        """Identifier recorded with every prediction: config + schema + fitted state."""
        payload = {
            "config": asdict(self.config),
            "schema_hash": self.schema.schema_hash,
            "state": self._state,
        }
        return f"pp-{self.config.version}-{sha256_json(payload)[:12]}"

    @property
    def requires_fit(self) -> bool:
        return self.config.imputation == "median" or self.config.scaling != "none"

    # -- core ---------------------------------------------------------------

    def _select(self, df: pd.DataFrame) -> pd.DataFrame:
        names = self.schema.feature_names
        missing = [c for c in names if c not in df.columns]
        if missing:
            raise PreprocessingError(f"input is missing required features: {missing}")
        X = df[names]
        non_numeric = [c for c in names if not pd.api.types.is_numeric_dtype(X[c])]
        if non_numeric:
            raise PreprocessingError(
                f"features must be numeric after ingestion; non-numeric columns: {non_numeric}"
            )
        return X.astype("float64")

    def fit(self, train_df: pd.DataFrame) -> "Preprocessor":
        """Learn transformation statistics from training data only."""
        if self.is_fitted:
            raise PreprocessingError("preprocessor is already fitted; create a new one to refit")
        X = self._select(train_df).replace([np.inf, -np.inf], np.nan)
        if len(X) == 0:
            raise PreprocessingError("cannot fit on an empty training set")
        state: dict[str, Any] = {
            "fitted_at": datetime.now(timezone.utc).isoformat(),
            "n_fit_rows": int(len(X)),
        }
        if self.config.imputation == "median":
            med = X.median()
            if med.isna().any():
                raise PreprocessingError(
                    f"features with no observed training values: {med[med.isna()].index.tolist()}"
                )
            state["medians"] = med.to_dict()
        Xi = self._impute(X, state)
        if self.config.scaling == "standard":
            std = Xi.std(ddof=0).replace(0.0, 1.0)
            state["mean"] = Xi.mean().to_dict()
            state["scale"] = std.to_dict()
        elif self.config.scaling == "minmax":
            lo, hi = Xi.min(), Xi.max()
            rng = (hi - lo).replace(0.0, 1.0)
            state["mean"] = lo.to_dict()
            state["scale"] = rng.to_dict()
        self._state = state
        return self

    def _impute(self, X: pd.DataFrame, state: dict[str, Any]) -> pd.DataFrame:
        if self.config.imputation == "median":
            return X.fillna(pd.Series(state["medians"]))
        if self.config.imputation == "zero":
            return X.fillna(0.0)
        return X

    def transform(self, df: pd.DataFrame) -> TransformOutput:
        """Apply frozen transformations. Rows that remain non-finite are rejected, not guessed."""
        if self.requires_fit and not self.is_fitted:
            raise PreprocessingError("preprocessor must be fitted on training data before transform")
        state = self._state or {}
        X = self._select(df).replace([np.inf, -np.inf], np.nan)
        X = self._impute(X, state)
        bad = X.isna().any(axis=1)
        X = X.loc[~bad]
        if self.config.scaling != "none":
            X = (X - pd.Series(state["mean"])) / pd.Series(state["scale"])
            X = X[self.schema.feature_names]
        return TransformOutput(X=X, rejected_index=df.index[bad.to_numpy()])

    # -- persistence (JSON only) -------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": asdict(self.config),
            "schema": self.schema.to_dict(),
            "state": self._state,
            "version_id": self.version_id,
        }

    def save(self, path: str | Path) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)
            fh.write("\n")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Preprocessor":
        pp = cls(FeatureSchema.from_dict(data["schema"]), PreprocessingConfig(**data["config"]))
        pp._state = data.get("state")
        if data.get("version_id") and data["version_id"] != pp.version_id:
            raise PreprocessingError("preprocessor state does not match its recorded version_id")
        return pp

    @classmethod
    def load(cls, path: str | Path) -> "Preprocessor":
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))
