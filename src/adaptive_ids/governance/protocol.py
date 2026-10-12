"""Candidate evaluation protocol: documented, versioned acceptance rules.

A candidate is compared with the baseline (the model active when the evaluation
starts) on the same labelled import, event by event, with the same truth labels.
"Attack" means any dataset label other than the candidate's benign label; a model
"flags" an event when its prediction is suspicious under its own decision rule
(the rule the platform uses to raise alerts).

Gates, in two groups:

* **validity** - enough labelled events (``min_labelled_events``) and enough of
  each class (``min_events_per_class``); each model failed to score at most
  ``max_failed_prediction_rate`` of them. The import must not be the file either
  model was trained from (checked before the evaluation starts). A failed
  validity gate means *insufficient evidence*; it cannot be overridden.
* **performance** - optional absolute requirements (``min_attack_recall``,
  ``max_false_positive_rate``) and, when a baseline exists, non-inferiority:
  the 95 % paired-bootstrap interval of (candidate - baseline) must stay within
  the margins (recall and F1 may not drop by more than ``recall_margin`` /
  ``f1_margin``; the false-positive rate may not rise by more than
  ``fpr_margin``). A failed performance gate means *fail*; an admin may still
  approve with a written justification, which is audited separately.

McNemar's test on the paired errors is reported for context only. A
significant difference is not a gate: the margins decide.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class EvaluationProtocol:
    version: str = "1.0.0"
    min_labelled_events: int = 200
    min_events_per_class: int = 30
    max_failed_prediction_rate: float = 0.01
    recall_margin: float = 0.01
    fpr_margin: float = 0.005
    f1_margin: float = 0.01
    min_attack_recall: float | None = None
    max_false_positive_rate: float | None = None
    bootstrap_iterations: int = 1000
    confidence: float = 0.95
    seed: int = 20261011
    mcnemar_alpha: float = 0.05
    reference_sample_size: int = 25

    def __post_init__(self) -> None:
        if not self.version or not isinstance(self.version, str):
            raise ProtocolError("version is required")
        if self.min_labelled_events < 20 or self.min_events_per_class < 5:
            raise ProtocolError("min_labelled_events must be >= 20 and min_events_per_class >= 5")
        if not 0 <= self.max_failed_prediction_rate < 0.5:
            raise ProtocolError("max_failed_prediction_rate must be within [0, 0.5)")
        for name in ("recall_margin", "fpr_margin", "f1_margin"):
            if not 0 <= getattr(self, name) < 0.5:
                raise ProtocolError(f"{name} must be within [0, 0.5)")
        for name in ("min_attack_recall", "max_false_positive_rate"):
            v = getattr(self, name)
            if v is not None and not 0 <= v <= 1:
                raise ProtocolError(f"{name} must be within [0, 1] or null")
        if not 200 <= self.bootstrap_iterations <= 20000:
            raise ProtocolError("bootstrap_iterations must be within [200, 20000]")
        if not 0.5 < self.confidence < 1:
            raise ProtocolError("confidence must be within (0.5, 1)")
        if not 0 < self.mcnemar_alpha < 0.5:
            raise ProtocolError("mcnemar_alpha must be within (0, 0.5)")
        if not 1 <= self.reference_sample_size <= 200:
            raise ProtocolError("reference_sample_size must be within [1, 200]")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "EvaluationProtocol":
        data = {k: v for k, v in dict(data or {}).items() if not k.startswith("_")}
        unknown = sorted(set(data) - {f.name for f in fields(cls)})
        if unknown:
            raise ProtocolError(f"unknown protocol settings: {unknown}")
        try:
            return cls(**data)
        except TypeError as exc:
            raise ProtocolError(str(exc)) from exc


def load_protocol(path: str | Path) -> EvaluationProtocol:
    """Load the protocol file; keys starting with '_' are comments."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProtocolError(f"cannot read evaluation protocol {path}: {exc}") from exc
    return EvaluationProtocol.from_dict(data)
