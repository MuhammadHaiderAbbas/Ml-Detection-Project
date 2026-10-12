"""Label-based performance per window (only where reliable labels exist)."""

from __future__ import annotations

from typing import Any

import numpy as np

from .config import DriftConfig


def window_performance(y_true: np.ndarray, y_pred: np.ndarray, benign: str | None) -> dict[str, Any]:
    n = int(len(y_true))
    if n == 0:
        return {"n_labelled": 0, "error_rate": None, "attack_recall": None, "false_positive_rate": None}
    yt, yp = y_true.astype(str), y_pred.astype(str)
    out: dict[str, Any] = {"n_labelled": n, "error_rate": float(np.mean(yt != yp))}
    if benign is not None:
        attack_t, attack_p = yt != benign, yp != benign
        tp = int(np.sum(attack_t & attack_p)); fn = int(np.sum(attack_t & ~attack_p))
        fp = int(np.sum(~attack_t & attack_p)); tn = int(np.sum(~attack_t & ~attack_p))
        out["attack_recall"] = tp / (tp + fn) if tp + fn else None
        out["false_positive_rate"] = fp / (fp + tn) if fp + tn else None
    return out


def degradation(ref: dict[str, Any], cur: dict[str, Any], cfg: DriftConfig) -> dict[str, Any]:
    if ref["n_labelled"] < cfg.perf_min_labels or cur["n_labelled"] < cfg.perf_min_labels:
        return {"severity": "insufficient_data", "error_rate_change": None}
    change = cur["error_rate"] - ref["error_rate"]
    sev = "major" if change >= cfg.perf_major else "moderate" if change >= cfg.perf_moderate else "none"
    return {"severity": sev, "error_rate_change": change}
