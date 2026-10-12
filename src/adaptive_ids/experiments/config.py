"""Experiment configuration (JSON) and validation."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..provenance import Provenance

SPLIT_METHODS = ("stratified_random", "chronological", "column", "all_test")
MODEL_MODES = ("trusted_artifact", "train")

# Estimators the runner may construct in "train" mode. Extending this list is a
# deliberate code change, not a config option.
TRAINABLE_ESTIMATORS = {
    "RandomForestClassifier": "sklearn.ensemble",
    "ExtraTreesClassifier": "sklearn.ensemble",
    "HistGradientBoostingClassifier": "sklearn.ensemble",
    "DecisionTreeClassifier": "sklearn.tree",
    "LogisticRegression": "sklearn.linear_model",
    "GaussianNB": "sklearn.naive_bayes",
}

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


class ConfigError(ValueError):
    pass


@dataclass
class ExperimentConfig:
    experiment_id: str
    objective: str
    provenance: str
    dataset: dict[str, Any]
    schema_path: str
    split: dict[str, Any]
    model: dict[str, Any]
    preprocessing: dict[str, Any] = field(default_factory=dict)
    decision: dict[str, Any] = field(default_factory=dict)
    evaluation: dict[str, Any] = field(default_factory=dict)
    reported_results: dict[str, Any] = field(default_factory=dict)
    output_dir: str = "experiments/runs"
    save_predictions: bool = True
    notes: str = ""

    def __post_init__(self) -> None:
        if not _ID_RE.match(self.experiment_id):
            raise ConfigError("experiment_id must be 1-100 chars of letters, digits, '.', '_' or '-'")
        try:
            Provenance(self.provenance)
        except ValueError as exc:
            raise ConfigError(f"provenance must be one of {[p.value for p in Provenance]}") from exc
        for key in ("path", "name", "version"):
            if not self.dataset.get(key):
                raise ConfigError(f"dataset.{key} is required")
        method = self.split.get("method")
        if method not in SPLIT_METHODS:
            raise ConfigError(f"split.method must be one of {SPLIT_METHODS}")
        if method == "stratified_random" and "seed" not in self.split:
            raise ConfigError("stratified_random split requires an explicit seed")
        if method == "column" and not self.split.get("column"):
            raise ConfigError("column split requires split.column")
        mode = self.model.get("mode")
        if mode not in MODEL_MODES:
            raise ConfigError(f"model.mode must be one of {MODEL_MODES}")
        if mode == "trusted_artifact":
            if not (self.model.get("manifest") and self.model.get("artifact_id")):
                raise ConfigError("trusted_artifact mode requires model.manifest and model.artifact_id")
        else:
            est = self.model.get("estimator")
            if est not in TRAINABLE_ESTIMATORS:
                raise ConfigError(f"model.estimator must be one of {sorted(TRAINABLE_ESTIMATORS)}")
            if method == "all_test":
                raise ConfigError("train mode cannot use the all_test split (no training rows)")
        if self.provenance == Provenance.ORIGINAL_DISSERTATION.value:
            raise ConfigError(
                "a new run cannot claim provenance 'original_dissertation'; "
                "use 'baseline_reproduction' and put the dissertation's numbers in reported_results"
            )
        if self.provenance == Provenance.BASELINE_REPRODUCTION.value and mode != "trusted_artifact":
            raise ConfigError(
                "baseline_reproduction must evaluate the original trusted artifact; "
                "retraining is a controlled_experiment"
            )

    @classmethod
    def load(cls, path: str | Path) -> "ExperimentConfig":
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        try:
            return cls(**data)
        except TypeError as exc:
            raise ConfigError(f"invalid experiment config: {exc}") from exc

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
