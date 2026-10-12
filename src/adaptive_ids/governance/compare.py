"""Paired candidate-vs-baseline comparison under an :class:`EvaluationProtocol`.

Both models are scored on the same events against the same labels, so the
comparison is paired. Every attack/benign metric depends only on how many
events fall into each (truth, candidate flag, baseline flag) cell, so the
paired bootstrap resamples those 8 cell counts from a multinomial. That is
exactly equivalent to resampling events with replacement, and it costs the same
for 1,000 events as for 1,000,000.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .protocol import EvaluationProtocol

METRICS = ("attack_recall", "false_positive_rate", "precision", "f1", "accuracy")
# direction: +1 = higher is better, -1 = lower is better
DIRECTION = {"attack_recall": 1, "false_positive_rate": -1, "precision": 1, "f1": 1, "accuracy": 1}


def _rates(tp, fp, tn, fn) -> dict[str, Any]:
    """Vectorised over arrays of counts; division by zero gives NaN."""
    tp, fp, tn, fn = (np.asarray(x, dtype="float64") for x in (tp, fp, tn, fn))
    with np.errstate(divide="ignore", invalid="ignore"):
        return {
            "attack_recall": tp / (tp + fn),
            "false_positive_rate": fp / (fp + tn),
            "precision": tp / (tp + fp),
            "f1": 2 * tp / (2 * tp + fp + fn),
            "accuracy": (tp + tn) / (tp + tn + fp + fn),
        }


def _model_counts(cells: np.ndarray, which: int) -> tuple[np.ndarray, ...]:
    """cells[..., t*4 + c*2 + b]; which=0 -> candidate flag (c), 1 -> baseline flag (b)."""
    c = cells.reshape(*cells.shape[:-1], 2, 2, 2)  # [t, c, b]
    flagged = c.sum(axis=-1 if which == 0 else -2)  # [..., t, flag]
    return flagged[..., 1, 1], flagged[..., 0, 1], flagged[..., 0, 0], flagged[..., 1, 0]  # tp, fp, tn, fn


def _clean(v: Any) -> float | None:
    v = float(v)
    return None if np.isnan(v) else round(v, 6)


def _mcnemar(cand_only_right: int, base_only_right: int) -> dict[str, Any]:
    from scipy.stats import binomtest, chi2

    n = cand_only_right + base_only_right
    if n == 0:
        return {"candidate_only_correct": 0, "baseline_only_correct": 0, "method": "none", "statistic": None,
                "p_value": 1.0}
    if n < 25:
        p = binomtest(cand_only_right, n, 0.5).pvalue
        return {"candidate_only_correct": cand_only_right, "baseline_only_correct": base_only_right,
                "method": "exact binomial", "statistic": None, "p_value": float(p)}
    stat = (abs(cand_only_right - base_only_right) - 1) ** 2 / n
    return {"candidate_only_correct": cand_only_right, "baseline_only_correct": base_only_right,
            "method": "chi-square, continuity corrected", "statistic": float(stat), "p_value": float(chi2.sf(stat, 1))}


@dataclass
class Comparison:
    verdict: str  # pass | fail | insufficient_evidence
    gates: list[dict[str, Any]]
    metrics: dict[str, Any]
    differences: dict[str, Any] = field(default_factory=dict)
    mcnemar: dict[str, Any] | None = None
    counts: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"verdict": self.verdict, "gates": self.gates, "metrics": self.metrics,
                "differences": self.differences, "mcnemar": self.mcnemar, "counts": self.counts}


def _gate(gid: str, kind: str, passed: bool | None, value: Any, threshold: Any, detail: str) -> dict[str, Any]:
    return {"id": gid, "kind": kind, "passed": passed, "value": value, "threshold": threshold, "detail": detail}


def compare_models(
    truth_attack: np.ndarray,
    cand_flag: np.ndarray,
    cand_ok: np.ndarray,
    protocol: EvaluationProtocol,
    base_flag: np.ndarray | None = None,
    base_ok: np.ndarray | None = None,
) -> Comparison:
    """Compare a candidate (and optionally a baseline) on the same labelled events.

    ``*_ok`` marks events the model scored successfully. Metrics are computed on
    events every compared model scored; failures are reported and gated.
    """
    truth = np.asarray(truth_attack, dtype=bool)
    cf, cok = np.asarray(cand_flag, dtype=bool), np.asarray(cand_ok, dtype=bool)
    has_base = base_flag is not None
    bf = np.asarray(base_flag, dtype=bool) if has_base else np.zeros_like(truth)
    bok = np.asarray(base_ok, dtype=bool) if has_base else np.ones_like(truth)
    n_total = int(truth.size)
    both = cok & bok
    t, c, b = truth[both], cf[both], bf[both]
    cells = np.bincount(t.astype(int) * 4 + c.astype(int) * 2 + b.astype(int), minlength=8).astype("int64")
    n = int(cells.sum())
    n_attack, n_benign = int(t.sum()), int((~t).sum())

    gates = [
        _gate("labelled_events", "validity", n >= protocol.min_labelled_events, n, protocol.min_labelled_events,
              "labelled events scored by every compared model"),
        _gate("attack_events", "validity", n_attack >= protocol.min_events_per_class, n_attack,
              protocol.min_events_per_class, "events labelled as attacks"),
        _gate("benign_events", "validity", n_benign >= protocol.min_events_per_class, n_benign,
              protocol.min_events_per_class, "events labelled benign"),
    ]
    fail_rates = {"candidate": 1 - float(cok.mean()) if n_total else 1.0}
    if has_base:
        fail_rates["baseline"] = 1 - float(bok.mean()) if n_total else 1.0
    for who, rate in fail_rates.items():
        gates.append(_gate(f"{who}_failed_predictions", "validity", rate <= protocol.max_failed_prediction_rate,
                           round(rate, 6), protocol.max_failed_prediction_rate,
                           f"share of labelled events the {who} could not score"))

    metrics: dict[str, Any] = {"candidate": {k: _clean(v) for k, v in _rates(*_model_counts(cells, 0)).items()}}
    metrics["candidate"]["confusion"] = dict(zip(("tp", "fp", "tn", "fn"), (int(x) for x in _model_counts(cells, 0))))
    if has_base:
        metrics["baseline"] = {k: _clean(v) for k, v in _rates(*_model_counts(cells, 1)).items()}
        metrics["baseline"]["confusion"] = dict(zip(("tp", "fp", "tn", "fn"), (int(x) for x in _model_counts(cells, 1))))

    cm = metrics["candidate"]
    if protocol.min_attack_recall is not None:
        v = cm["attack_recall"]
        gates.append(_gate("min_attack_recall", "performance", v is not None and v >= protocol.min_attack_recall, v,
                           protocol.min_attack_recall, "candidate attack recall (detection rate)"))
    if protocol.max_false_positive_rate is not None:
        v = cm["false_positive_rate"]
        gates.append(_gate("max_false_positive_rate", "performance",
                           v is not None and v <= protocol.max_false_positive_rate, v,
                           protocol.max_false_positive_rate, "candidate false-positive rate"))

    differences: dict[str, Any] = {}
    mcnemar = None
    if has_base and n > 0:
        rng = np.random.default_rng(protocol.seed)
        boot = rng.multinomial(n, cells / n, size=protocol.bootstrap_iterations)
        rc, rb = _rates(*_model_counts(boot, 0)), _rates(*_model_counts(boot, 1))
        lo_q, hi_q = (1 - protocol.confidence) / 2, 1 - (1 - protocol.confidence) / 2
        point_c, point_b = _rates(*_model_counts(cells, 0)), _rates(*_model_counts(cells, 1))
        for m in METRICS:
            d = rc[m] - rb[m]
            d = d[~np.isnan(d)]
            point = float(point_c[m] - point_b[m])
            differences[m] = {
                "difference": _clean(point),
                "ci_low": _clean(np.quantile(d, lo_q)) if d.size else None,
                "ci_high": _clean(np.quantile(d, hi_q)) if d.size else None,
                "better_when": "higher" if DIRECTION[m] > 0 else "lower",
            }
        margins = (("attack_recall", "attack recall", protocol.recall_margin), ("f1", "F1", protocol.f1_margin))
        for m, label, margin in margins:
            lo = differences[m]["ci_low"]
            gates.append(_gate(f"non_inferior_{m}", "performance", lo is not None and lo >= -margin, lo, -margin,
                               f"{label} drops by at most {margin * 100:.1f} pp (lower {protocol.confidence:.0%} bound of "
                               "candidate - baseline)"))
        hi = differences["false_positive_rate"]["ci_high"]
        gates.append(_gate("non_inferior_false_positive_rate", "performance",
                           hi is not None and hi <= protocol.fpr_margin, hi, protocol.fpr_margin,
                           f"false-positive rate rises by at most {protocol.fpr_margin * 100:.1f} pp (upper "
                           f"{protocol.confidence:.0%} bound of candidate - baseline)"))
        cand_right, base_right = (c == t), (b == t)
        mcnemar = _mcnemar(int(np.sum(cand_right & ~base_right)), int(np.sum(~cand_right & base_right)))
        mcnemar["significant"] = mcnemar["p_value"] < protocol.mcnemar_alpha
        mcnemar["alpha"] = protocol.mcnemar_alpha

    if any(g["passed"] is False for g in gates if g["kind"] == "validity"):
        verdict = "insufficient_evidence"
    elif any(g["passed"] is False for g in gates if g["kind"] == "performance"):
        verdict = "fail"
    else:
        verdict = "pass"
    counts = {"labelled_events": n_total, "compared_events": n, "attack_events": n_attack, "benign_events": n_benign,
              "failed_prediction_rate": {k: round(v, 6) for k, v in fail_rates.items()}}
    return Comparison(verdict, gates, metrics, differences, mcnemar, counts)
