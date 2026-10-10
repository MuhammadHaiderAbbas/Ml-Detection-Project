"""Classification metrics for imbalanced intrusion-detection data.

Reports per-class metrics alongside macro/weighted averages, and a binary
"attack vs benign" view (false-positive and false-negative rates) when the
benign label is known. Rows the model did not score (rejected) are excluded
from metric computation and reported separately — they are never counted as
correct or incorrect predictions.
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    precision_recall_fscore_support,
)


def _safe_div(a: float, b: float) -> float | None:
    return float(a / b) if b else None


def binary_rates(y_true_attack: np.ndarray, y_pred_attack: np.ndarray) -> dict[str, Any]:
    """Rates where the positive class is 'attack' (anything not benign)."""
    tp = int(np.sum(y_true_attack & y_pred_attack))
    tn = int(np.sum(~y_true_attack & ~y_pred_attack))
    fp = int(np.sum(~y_true_attack & y_pred_attack))
    fn = int(np.sum(y_true_attack & ~y_pred_attack))
    return {
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "precision": _safe_div(tp, tp + fp),
        "recall_detection_rate": _safe_div(tp, tp + fn),
        "f1": _safe_div(2 * tp, 2 * tp + fp + fn),
        "false_positive_rate": _safe_div(fp, fp + tn),
        "false_negative_rate": _safe_div(fn, fn + tp),
        "accuracy": _safe_div(tp + tn, tp + tn + fp + fn),
    }


def classification_metrics(
    y_true: Sequence[Any],
    y_pred: Sequence[Any],
    *,
    labels: Sequence[Any] | None = None,
    benign_label: Any = None,
) -> dict[str, Any]:
    y_true = np.asarray([str(v) for v in y_true], dtype=object)
    y_pred = np.asarray([str(v) for v in y_pred], dtype=object)
    if len(y_true) != len(y_pred):
        raise ValueError("y_true and y_pred have different lengths")
    if len(y_true) == 0:
        raise ValueError("cannot compute metrics on zero scored rows")
    if labels is None:
        labels = sorted(set(y_true) | set(y_pred))
    labels = [str(l) for l in labels]

    p, r, f, s = precision_recall_fscore_support(y_true, y_pred, labels=labels, zero_division=0)
    per_class = {
        lab: {"precision": float(p[i]), "recall": float(r[i]), "f1": float(f[i]), "support": int(s[i])}
        for i, lab in enumerate(labels)
    }
    averages = {}
    for avg in ("macro", "weighted"):
        ap, ar, af, _ = precision_recall_fscore_support(
            y_true, y_pred, labels=labels, average=avg, zero_division=0
        )
        averages[avg] = {"precision": float(ap), "recall": float(ar), "f1": float(af)}

    out: dict[str, Any] = {
        "n_scored": int(len(y_true)),
        "labels": labels,
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "averages": averages,
        "per_class": per_class,
        "confusion_matrix": {
            "labels": labels,
            "rows_true_cols_pred": confusion_matrix(y_true, y_pred, labels=labels).tolist(),
        },
        "notes": [
            "zero_division=0: a class with no predictions reports precision 0.",
        ],
    }
    if benign_label is not None:
        b = str(benign_label)
        if b not in labels:
            out["notes"].append(f"benign label {b!r} not present; binary attack/benign view omitted")
        else:
            out["binary_attack_vs_benign"] = {
                "benign_label": b,
                **binary_rates(y_true != b, y_pred != b),
            }
    return out
