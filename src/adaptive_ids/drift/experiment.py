"""Controlled drift experiments on SYNTHETIC data with a known drift point.

Measures, per detector, the detection delay (events between the true drift
start and the first detection), false alarms (detections before the drift
start), misses, and computational overhead, so drift-aware monitoring can be
evaluated rather than asserted. Results describe the synthetic generator only.

Modes:
* ``none``    - no drift (estimates the false-alarm rate);
* ``sudden``  - benign traffic shifts at the drift point (feature drift);
* ``gradual`` - the same shift ramps up in steps after the drift point;
* ``concept`` - inputs unchanged, but a share of benign-looking flows is
  labelled as attacks after the drift point (P(y|x) changes; needs labels).
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..experiments.environment import capture_environment
from ..provenance import PROVENANCE_BANNERS, Provenance
from ..research.synthetic import FEATURES, generate_synthetic_flows
from .analysis import DriftFrames, analyze
from .config import DriftConfig

MODES = ("none", "sudden", "gradual", "concept")
CLASSES_OK = ("Benign", "SYNTH_DoS", "SYNTH_PortScan")


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["orig_index"] = np.arange(len(df))
    df = df[df["Label"].isin(CLASSES_OK)]
    for f in FEATURES:
        df[f] = pd.to_numeric(df[f], errors="coerce")
    df = df.dropna(subset=FEATURES)
    df["occurred_at"] = pd.to_datetime(df["Timestamp"], utc=True)
    return df.sort_values("occurred_at", kind="stable").reset_index(drop=True)


def run_trial(mode: str, *, seed: int, n_reference: int = 4000, n_current: int = 6000, drift_at: float = 0.5,
              strength: float = 0.6, concept_fraction: float = 0.3, window_size: int = 500,
              cfg: DriftConfig | None = None) -> dict[str, Any]:
    from sklearn.ensemble import RandomForestClassifier

    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    cfg = cfg or DriftConfig()
    ref = _clean(generate_synthetic_flows(n_reference, seed=seed, inject_invalid_rows=False))
    model = RandomForestClassifier(n_estimators=50, random_state=seed, n_jobs=1).fit(ref[FEATURES], ref["Label"])
    drift = mode in ("sudden", "gradual")
    cur = _clean(generate_synthetic_flows(
        n_current, seed=seed + 1000, inject_invalid_rows=False,
        drift_after_fraction=drift_at if drift else None, drift_strength=strength,
        drift_mode="gradual" if mode == "gradual" else "sudden",
        start=datetime(2026, 2, 1, tzinfo=timezone.utc),
    ))
    drift_from = int(n_current * drift_at)
    if mode == "concept":
        rng = np.random.default_rng(seed + 7)
        after = (cur["orig_index"] >= drift_from) & (cur["Label"] == "Benign")
        flip = after & (rng.random(len(cur)) < concept_fraction)
        cur.loc[flip, "Label"] = "SYNTH_DoS"  # stealthy attack that looks like benign traffic
    true_pos = None if mode == "none" else int((cur["orig_index"] >= drift_from).idxmax())

    for df in (ref, cur):
        df["predicted_class"] = model.predict(df[FEATURES])
        df["status"] = "ok"
        df["is_suspicious"] = df["predicted_class"] != "Benign"
        df["label"] = df["Label"]

    t0 = time.perf_counter()
    res = analyze(DriftFrames(ref, cur, FEATURES, "Benign"), {"mode": "events", "size": window_size}, cfg)
    elapsed = time.perf_counter() - t0

    # Detection positions (index into the current stream at which each detector fires).
    detections: dict[str, list[int]] = {"feature_windows": [], "prediction_windows": [], "adwin_suspicious": [], "adwin_error": []}
    for w in res.windows:
        end = w["index"] * window_size + w["n_events"]
        if w["drifted_features"]:
            detections["feature_windows"].append(end)
        if w["prediction"] and w["prediction"]["severity"] in ("moderate", "major"):
            detections["prediction_windows"].append(end)
    detections["adwin_suspicious"] = [c["position"] for c in res.overall["streaming"].get("suspicious_rate", [])]
    detections["adwin_error"] = [c["position"] for c in res.overall["streaming"].get("error_rate", [])
                                 if c["direction"] == "increase"]

    per_detector = {}
    for name, pos in detections.items():
        if true_pos is None:
            per_detector[name] = {"false_alarms": len(pos), "detected": None, "delay_events": None}
            continue
        before = [p for p in pos if p < true_pos]
        after = [p for p in pos if p >= true_pos]
        per_detector[name] = {"false_alarms": len(before), "detected": bool(after),
                              "delay_events": (after[0] - true_pos) if after else None}
    return {
        "mode": mode, "seed": seed, "true_drift_position": true_pos, "n_current": int(len(cur)),
        "summary": res.summary, "detectors": per_detector,
        "overhead": {"analysis_s": elapsed, "us_per_event": elapsed / max(1, len(cur)) * 1e6, **res.timings},
        "label_error_rate_after": float((cur.loc[cur.index >= (true_pos or 0), "label"]
                                         != cur.loc[cur.index >= (true_pos or 0), "predicted_class"]).mean()),
    }


def run_experiment(modes: list[str], *, repeats: int = 3, seed: int = 11, out_dir: str | Path = "experiments/runs",
                   **kwargs: Any) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    trials = [run_trial(m, seed=seed + r, **kwargs) for m in modes for r in range(repeats)]
    agg: dict[str, Any] = {}
    for m in modes:
        ts = [t for t in trials if t["mode"] == m]
        agg[m] = {}
        for det in ts[0]["detectors"]:
            vals = [t["detectors"][det] for t in ts]
            delays = [v["delay_events"] for v in vals if v["delay_events"] is not None]
            agg[m][det] = {
                "detection_rate": None if m == "none" else sum(bool(v["detected"]) for v in vals) / len(vals),
                "mean_delay_events": float(np.mean(delays)) if delays else None,
                "false_alarms_total": sum(v["false_alarms"] for v in vals),
            }
        agg[m]["mean_us_per_event"] = float(np.mean([t["overhead"]["us_per_event"] for t in ts]))
    result = {
        "experiment": "controlled-drift",
        "provenance": Provenance.SYNTHETIC_DEMO.value,
        "banner": PROVENANCE_BANNERS[Provenance.SYNTHETIC_DEMO],
        "started_at": started.isoformat(), "modes": modes, "repeats": repeats, "seed": seed, "params": kwargs,
        "config": (kwargs.get("cfg") or DriftConfig()).to_dict(),
        "aggregate": agg, "trials": trials, "environment": capture_environment(),
        "limitations": [
            "Synthetic generator only: delays and false-alarm counts describe this generator, not real traffic.",
            "Window-based detectors can only fire at window ends, so their delay includes up to one window of waiting.",
            "Concept drift is only observable through labels; without labels it cannot be detected.",
            f"{repeats} repeat(s) per mode; small numbers of repeats give imprecise rates.",
        ],
    }
    result["params"].pop("cfg", None)
    run_dir = Path(out_dir) / f"drift-experiment-{started.strftime('%Y%m%dT%H%M%SZ')}"
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "result.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    (run_dir / "report.md").write_text(render_report(result), encoding="utf-8")
    result["run_dir"] = str(run_dir)
    return result


def render_report(r: dict[str, Any]) -> str:
    def f(v, d=0):
        return "n/a" if v is None else (f"{v:.{d}f}" if isinstance(v, float) else str(v))

    lines = [
        "# Controlled drift experiment", "", f"> **{r['banner']}**", "",
        f"- Started: {r['started_at']}", f"- Modes: {', '.join(r['modes'])}; repeats per mode: {r['repeats']}; base seed {r['seed']}",
        f"- Parameters: {r['params']}", f"- Drift thresholds: {r['config']}", "",
        "## Results by mode and detector", "",
        "| Mode | Detector | Detection rate | Mean delay (events) | False alarms (total) |", "|---|---|---|---|---|",
    ]
    for m, dets in r["aggregate"].items():
        for name, v in dets.items():
            if name == "mean_us_per_event":
                continue
            lines.append(f"| {m} | {name} | {f(v['detection_rate'], 2)} | {f(v['mean_delay_events'], 0)} | {v['false_alarms_total']} |")
    lines += ["", "## Overhead", ""] + [f"- {m}: {v['mean_us_per_event']:.1f} µs per event (full analysis, CPU)" for m, v in r["aggregate"].items()]
    lines += ["", "## Limitations", ""] + [f"- {x}" for x in r["limitations"]] + [""]
    return "\n".join(lines)
