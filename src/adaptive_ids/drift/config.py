"""Drift-detection configuration: documented, versioned thresholds.

Rules (applied per signal):

* ``insufficient_data`` - fewer than ``min_window_events`` observations in either
  sample (or fewer than ``perf_min_labels`` labelled events for performance).
* Feature / prediction distribution drift uses an *effect size* (PSI) gated by a
  significance test (KS for numeric features, chi-square for class
  distributions) after Bonferroni correction across the features tested:
  ``major`` if PSI >= ``psi_major`` and p_adj < ``alpha``; ``moderate`` if
  PSI >= ``psi_moderate`` and p_adj < ``alpha``; otherwise ``none``.
  The p-value alone is never used: with large samples it flags trivial shifts.
* Performance degradation compares the error rate of the current data with the
  reference data (labels required): ``major`` if it rises by >= ``perf_major``,
  ``moderate`` if by >= ``perf_moderate`` (absolute, 0-1 scale).
* ADWIN (River) watches bounded 0/1 streams in event-time order: the
  suspicious-prediction indicator (prediction drift) and, when labels exist,
  the error indicator (performance). ``adwin_delta`` is its confidence
  parameter; smaller is more conservative.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any

SEVERITIES = ("none", "moderate", "major", "insufficient_data")


class DriftConfigError(ValueError):
    pass


@dataclass(frozen=True)
class DriftConfig:
    version: str = "1.0.0"
    psi_bins: int = 10
    psi_moderate: float = 0.10
    psi_major: float = 0.25
    alpha: float = 0.01
    min_window_events: int = 200
    perf_min_labels: int = 100
    perf_moderate: float = 0.02
    perf_major: float = 0.05
    adwin_delta: float = 0.002
    max_adwin_events: int = 10

    def __post_init__(self) -> None:
        if not 2 <= self.psi_bins <= 50:
            raise DriftConfigError("psi_bins must be within [2, 50]")
        if not 0 < self.psi_moderate < self.psi_major:
            raise DriftConfigError("require 0 < psi_moderate < psi_major")
        if not 0 < self.alpha < 0.5:
            raise DriftConfigError("alpha must be within (0, 0.5)")
        if self.min_window_events < 20 or self.perf_min_labels < 20:
            raise DriftConfigError("minimum sample sizes must be at least 20")
        if not 0 < self.perf_moderate < self.perf_major < 1:
            raise DriftConfigError("require 0 < perf_moderate < perf_major < 1")
        if not 0 < self.adwin_delta < 1:
            raise DriftConfigError("adwin_delta must be within (0, 1)")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "DriftConfig":
        data = dict(data or {})
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(data) - known)
        if unknown:
            raise DriftConfigError(f"unknown drift settings: {unknown}")
        try:
            return cls(**data)
        except TypeError as exc:
            raise DriftConfigError(str(exc)) from exc
