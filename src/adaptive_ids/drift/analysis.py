"""Drift analysis: compare a current sample against a reference sample.

Four signals are kept separate (spec section 10):

* **feature drift** - per-feature distribution change (PSI + KS, Bonferroni);
* **prediction drift** - change in the model's output distribution (class mix,
  suspicious rate; chi-square + PSI; ADWIN on the suspicious indicator);
* **performance degradation** - error-rate change, only where labels exist;
* **suspected concept drift** - performance degradation *without* feature
  drift, i.e. the input-label relationship appears to have changed. This is an
  interpretation of the other signals, never proof, and needs labels.

A drift signal is not evidence of an attack or of model failure.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .config import DriftConfig
from .performance import degradation, window_performance
from .stats import bonferroni, categorical_drift, classify, numeric_drift
from .streaming import adwin_changes

ORDER = {"none": 0, "insufficient_data": 0, "moderate": 1, "major": 2}


@dataclass
class DriftFrames:
    """Inputs: feature columns plus optional ``occurred_at``, ``predicted_class``,
    ``is_suspicious`` (bool), ``status`` (prediction status) and ``label``."""

    reference: pd.DataFrame
    current: pd.DataFrame
    features: list[str]
    benign_label: str | None = None


@dataclass
class DriftResult:
    overall: dict[str, Any]
    windows: list[dict[str, Any]]
    events: list[dict[str, Any]]
    summary: dict[str, Any]
    timings: dict[str, float] = field(default_factory=dict)


def _order(df: pd.DataFrame) -> pd.DataFrame:
    if "occurred_at" in df.columns:
        return df.sort_values("occurred_at", kind="stable", na_position="last").reset_index(drop=True)
    return df.reset_index(drop=True)


def _windows(df: pd.DataFrame, spec: dict[str, Any]) -> list[tuple[int, pd.DataFrame]]:
    mode = spec.get("mode", "events")
    if mode == "events":
        size = int(spec.get("size", 500))
        if size < 20:
            raise ValueError("window size must be at least 20 events")
        return [(i, df.iloc[s:s + size]) for i, s in enumerate(range(0, len(df), size))]
    if mode == "time":
        if "occurred_at" not in df.columns or df["occurred_at"].isna().all():
            raise ValueError("time windows need event timestamps")
        freq = {"hour": "h", "day": "D", "week": "W"}.get(spec.get("bucket", "day"))
        if freq is None:
            raise ValueError("bucket must be hour, day or week")
        ts = pd.to_datetime(df["occurred_at"], utc=True)
        keys = ts.dt.floor(freq) if freq != "W" else ts.dt.tz_convert(None).dt.to_period("W").dt.start_time
        groups = [(k, g) for k, g in df.groupby(keys, sort=True)]
        return [(i, g) for i, (_, g) in enumerate(groups)]
    raise ValueError("window mode must be 'events' or 'time'")


def _scored(df: pd.DataFrame) -> pd.DataFrame:
    if "predicted_class" not in df.columns:
        return df.iloc[0:0]
    ok = df["predicted_class"].notna()
    if "status" in df.columns:
        ok &= df["status"] == "ok"
    return df[ok]


def _perf(df: pd.DataFrame, benign: str | None) -> dict[str, Any]:
    s = _scored(df)
    if "label" not in s.columns or "predicted_class" not in s.columns:
        return window_performance(np.array([]), np.array([]), benign)
    s = s[s["label"].notna()]
    return window_performance(s["label"].to_numpy(), s["predicted_class"].to_numpy(), benign)


def _feature_block(ref: pd.DataFrame, cur: pd.DataFrame, features: list[str], cfg: DriftConfig, keep_bins: bool) -> dict[str, Any]:
    per = {f: numeric_drift(ref[f], cur[f], cfg, keep_bins=keep_bins) for f in features}
    padj = bonferroni([per[f]["ks_p"] for f in features])
    for f, p in zip(features, padj):
        per[f]["ks_p_adj"] = p
        per[f]["severity"] = classify(per[f]["psi"], p, per[f]["n_ref"], per[f]["n_cur"], cfg)
    return per


def _prediction_block(ref: pd.DataFrame, cur: pd.DataFrame, cfg: DriftConfig) -> dict[str, Any] | None:
    rs, cs = _scored(ref), _scored(cur)
    if rs.empty and cs.empty:
        return None
    d = categorical_drift(rs["predicted_class"].tolist(), cs["predicted_class"].tolist(), cfg)
    d["severity"] = classify(d["psi"], d["chi2_p"], d["n_ref"], d["n_cur"], cfg)
    if "is_suspicious" in rs.columns:
        d["suspicious_rate_ref"] = float(rs["is_suspicious"].mean()) if len(rs) else None
        d["suspicious_rate_cur"] = float(cs["is_suspicious"].mean()) if len(cs) else None
    return d


def analyze(frames: DriftFrames, window_spec: dict[str, Any], cfg: DriftConfig | None = None) -> DriftResult:
    cfg = cfg or DriftConfig()
    t0 = time.perf_counter()
    feats = frames.features
    missing = [f for f in feats if f not in frames.reference.columns or f not in frames.current.columns]
    if missing:
        raise ValueError(f"features missing from the data: {missing}")
    if not feats:
        raise ValueError("select at least one feature")
    ref, cur = _order(frames.reference), _order(frames.current)
    benign = frames.benign_label

    # ---- overall comparison ------------------------------------------------
    overall_features = _feature_block(ref, cur, feats, cfg, keep_bins=True)
    overall_pred = _prediction_block(ref, cur, cfg)
    perf_ref, perf_cur = _perf(ref, benign), _perf(cur, benign)
    perf_overall = {"reference": perf_ref, "current": perf_cur, **degradation(perf_ref, perf_cur, cfg)}
    t_overall = time.perf_counter()

    # ---- windows over the current sample -----------------------------------
    windows = []
    for idx, w in _windows(cur, window_spec):
        per = _feature_block(ref, w, feats, cfg, keep_bins=False)
        drifted = [f for f in feats if per[f]["severity"] in ("moderate", "major")]
        pred = _prediction_block(ref, w, cfg)
        perf = _perf(w, benign)
        ts = w["occurred_at"] if "occurred_at" in w.columns else pd.Series(dtype="datetime64[ns, UTC]")
        windows.append({
            "index": idx, "n_events": int(len(w)),
            "start": None if ts.dropna().empty else pd.Timestamp(ts.dropna().min()).isoformat(),
            "end": None if ts.dropna().empty else pd.Timestamp(ts.dropna().max()).isoformat(),
            "features": {f: {k: per[f][k] for k in ("psi", "ks_d", "ks_p_adj", "severity", "n_cur")} for f in feats},
            "max_feature_psi": max((per[f]["psi"] or 0.0) for f in feats),
            "drifted_features": drifted,
            "prediction": None if pred is None else {k: pred.get(k) for k in ("psi", "chi2_p", "severity", "suspicious_rate_cur", "n_cur")},
            "performance": {**perf, **degradation(perf_ref, perf, cfg)},
        })
    t_windows = time.perf_counter()

    # ---- streaming detectors (current sample, event-time order) ------------
    stream: dict[str, Any] = {}
    cs = _scored(cur)
    if "is_suspicious" in cs.columns and len(cs):
        stream["suspicious_rate"] = adwin_changes(cs["is_suspicious"].astype(float).to_numpy(), cfg.adwin_delta,
                                                  max_events=cfg.max_adwin_events)
    if "label" in cs.columns and cs["label"].notna().sum() >= cfg.perf_min_labels:
        lab = cs[cs["label"].notna()]
        err = (lab["label"].astype(str) != lab["predicted_class"].astype(str)).astype(float).to_numpy()
        stream["error_rate"] = adwin_changes(err, cfg.adwin_delta, max_events=cfg.max_adwin_events)
    t_stream = time.perf_counter()

    # ---- events and verdicts ------------------------------------------------
    events: list[dict[str, Any]] = []
    feature_drifted = {f: v for f, v in overall_features.items() if v["severity"] in ("moderate", "major")}
    for f, v in sorted(feature_drifted.items(), key=lambda kv: -(kv[1]["psi"] or 0)):
        onset = next((w for w in windows if w["features"][f]["severity"] in ("moderate", "major")), None)
        events.append({
            "drift_type": "feature", "signal": f, "severity": v["severity"],
            "rule": f"PSI {v['psi']:.3f} >= {cfg.psi_moderate if v['severity'] == 'moderate' else cfg.psi_major} "
                    f"and KS p_adj {v['ks_p_adj']:.2g} < {cfg.alpha}",
            "window_index": onset["index"] if onset else None, "detected_at": onset["start"] if onset else None,
            "details": {k: v.get(k) for k in ("psi", "ks_d", "ks_p_adj", "ref_mean", "cur_mean", "ref_median", "cur_median")},
        })
    if overall_pred and overall_pred["severity"] in ("moderate", "major"):
        onset = next((w for w in windows if w["prediction"] and w["prediction"]["severity"] in ("moderate", "major")), None)
        events.append({
            "drift_type": "prediction", "signal": "predicted_class_distribution", "severity": overall_pred["severity"],
            "rule": f"class-mix PSI {overall_pred['psi']:.3f} with chi-square p {overall_pred['chi2_p']:.2g} < {cfg.alpha}",
            "window_index": onset["index"] if onset else None, "detected_at": onset["start"] if onset else None,
            "details": {k: overall_pred.get(k) for k in ("psi", "chi2_p", "js_distance", "suspicious_rate_ref", "suspicious_rate_cur")},
        })
    ts_cur = cs["occurred_at"].reset_index(drop=True) if "occurred_at" in cs.columns else None
    for name, kind in (("suspicious_rate", "prediction"), ("error_rate", "performance")):
        for ch in stream.get(name, []):
            if kind == "performance" and ch["direction"] != "increase":
                continue  # a falling error rate is not degradation
            at = ts_cur.iloc[ch["position"]] if ts_cur is not None and ch["position"] < len(ts_cur) else None
            events.append({
                "drift_type": kind, "signal": f"adwin:{name}", "severity": "moderate",
                "rule": f"ADWIN (delta={cfg.adwin_delta}) change in {name.replace('_', ' ')}: "
                        f"{ch['mean_before']:.3f} -> {ch['mean_after']:.3f}" if ch["mean_before"] is not None else
                        f"ADWIN (delta={cfg.adwin_delta}) change in {name.replace('_', ' ')}",
                "window_index": None, "detected_at": None if at is None or pd.isna(at) else pd.Timestamp(at).isoformat(),
                "details": ch,
            })
    perf_sev = perf_overall["severity"]
    if perf_sev in ("moderate", "major"):
        events.append({
            "drift_type": "performance", "signal": "error_rate", "severity": perf_sev,
            "rule": f"error rate rose by {perf_overall['error_rate_change']:.3f} "
                    f"(>= {cfg.perf_moderate if perf_sev == 'moderate' else cfg.perf_major})",
            "window_index": None, "detected_at": None,
            "details": {"reference": perf_ref, "current": perf_cur},
        })
        if not feature_drifted:
            events.append({
                "drift_type": "concept", "signal": "error_rate_without_feature_drift", "severity": perf_sev,
                "rule": "performance degraded while no feature drift was detected: the input-label relationship may "
                        "have changed (suspected concept drift; not proof)",
                "window_index": None, "detected_at": None, "details": {"error_rate_change": perf_overall["error_rate_change"]},
            })

    def verdict(kind: str) -> dict[str, Any]:
        ev = [e for e in events if e["drift_type"] == kind]
        if ev:
            sev = max((e["severity"] for e in ev), key=lambda s: ORDER.get(s, 0))
            return {"status": "detected", "severity": sev, "events": len(ev)}
        if kind == "feature":
            insufficient = all(v["severity"] == "insufficient_data" for v in overall_features.values())
            return {"status": "insufficient_data" if insufficient else "not_detected"}
        if kind == "prediction":
            return {"status": "not_assessable" if overall_pred is None else
                    "insufficient_data" if overall_pred["severity"] == "insufficient_data" else "not_detected"}
        if perf_sev == "insufficient_data":
            return {"status": "not_assessable", "reason": "needs labelled events in both samples"}
        return {"status": "not_detected"}

    summary = {
        "feature": verdict("feature"), "prediction": verdict("prediction"),
        "performance": verdict("performance"), "concept": verdict("concept"),
        "n_reference": int(len(ref)), "n_current": int(len(cur)), "n_windows": len(windows),
        "features_tested": len(feats), "features_drifted": sorted(feature_drifted),
        "interpretation": "Drift signals describe change in data or model behaviour. They are not evidence of an attack "
                          "and do not by themselves show model failure; nothing is retrained or promoted automatically.",
    }
    t_end = time.perf_counter()
    timings = {"overall_ms": (t_overall - t0) * 1e3, "windows_ms": (t_windows - t_overall) * 1e3,
               "streaming_ms": (t_stream - t_windows) * 1e3, "total_ms": (t_end - t0) * 1e3}
    overall = {"features": overall_features, "prediction": overall_pred, "performance": perf_overall, "streaming": stream}
    return DriftResult(overall=overall, windows=windows, events=events, summary=summary, timings=timings)
