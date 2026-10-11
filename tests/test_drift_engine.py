from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from adaptive_ids.drift import DriftConfig, DriftConfigError, DriftFrames, analyze
from adaptive_ids.drift.stats import binned_proportions, bonferroni, categorical_drift, numeric_drift, psi, quantile_edges
from adaptive_ids.drift.streaming import adwin_changes


def frame(n, seed, shift=0.0, labels=True, preds=True, error_rate=0.0):
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({"a": rng.normal(shift, 1, n), "b": rng.integers(0, 4, n).astype(float)})
    df["occurred_at"] = pd.date_range("2026-01-01", periods=n, freq="min", tz="UTC")
    truth = np.where(rng.random(n) < 0.2, "Attack", "Benign")
    if labels:
        df["label"] = truth
    if preds:
        wrong = rng.random(n) < error_rate
        df["predicted_class"] = np.where(wrong, np.where(truth == "Benign", "Attack", "Benign"), truth)
        df["status"] = "ok"
        df["is_suspicious"] = df["predicted_class"] != "Benign"
    return df


def test_psi_properties():
    p = np.array([0.25, 0.25, 0.5])
    assert psi(p, p) == pytest.approx(0.0)
    assert psi(p, np.array([0.5, 0.25, 0.25])) > 0.1
    edges = quantile_edges(np.array([1.0] * 50 + [2.0] * 50), 10)
    assert len(edges) <= 3  # 9 interior quantiles of a two-valued feature collapse to {1, 1.5, 2}
    assert binned_proportions(np.array([1.0, 2.0, 3.0]), np.array([1.5])).tolist() == pytest.approx([1 / 3, 2 / 3])


def test_numeric_and_categorical_drift():
    cfg = DriftConfig()
    same = numeric_drift(pd.Series(np.random.default_rng(0).normal(0, 1, 2000)), pd.Series(np.random.default_rng(1).normal(0, 1, 2000)), cfg)
    moved = numeric_drift(pd.Series(np.random.default_rng(0).normal(0, 1, 2000)), pd.Series(np.random.default_rng(1).normal(1, 1, 2000)), cfg, keep_bins=True)
    assert same["psi"] < 0.1 and moved["psi"] > 0.25 and moved["ks_p"] < 1e-6
    assert len(moved["bins"]["ref"]) == len(moved["bins"]["edges"]) + 1
    c = categorical_drift(["a"] * 900 + ["b"] * 100, ["a"] * 500 + ["b"] * 500, cfg)
    assert c["psi"] > 0.25 and c["chi2_p"] < 1e-6
    assert bonferroni([0.01, None, 0.2]) == [0.02, None, 0.4]


def test_null_case_raises_nothing_and_shift_is_detected():
    ref = frame(3000, 1)
    quiet = analyze(DriftFrames(ref, frame(3000, 2), ["a", "b"], "Benign"), {"mode": "events", "size": 500})
    assert quiet.events == [] and quiet.summary["feature"]["status"] == "not_detected"
    loud = analyze(DriftFrames(ref, frame(3000, 3, shift=1.0), ["a", "b"], "Benign"), {"mode": "events", "size": 500})
    assert loud.summary["feature"]["status"] == "detected" and loud.summary["features_drifted"] == ["a"]
    ev = loud.events[0]
    assert ev["drift_type"] == "feature" and ev["window_index"] == 0 and "PSI" in ev["rule"]


def test_concept_drift_only_suspected_when_performance_drops_without_feature_drift():
    ref = frame(3000, 1, error_rate=0.02)
    cur = frame(3000, 2, error_rate=0.15)  # same inputs, worse predictions
    r = analyze(DriftFrames(ref, cur, ["a", "b"], "Benign"), {"mode": "events", "size": 500})
    assert r.summary["feature"]["status"] == "not_detected"
    assert r.summary["performance"]["status"] == "detected"
    assert r.summary["concept"]["status"] == "detected"
    concept = [e for e in r.events if e["drift_type"] == "concept"][0]
    assert "not proof" in concept["rule"]
    # with feature drift present, the same degradation is NOT labelled concept drift
    r2 = analyze(DriftFrames(ref, frame(3000, 2, shift=1.0, error_rate=0.15), ["a", "b"], "Benign"), {"mode": "events", "size": 500})
    assert r2.summary["performance"]["status"] == "detected" and r2.summary["concept"]["status"] == "not_detected"


def test_missing_labels_or_predictions_are_not_assessable():
    r = analyze(DriftFrames(frame(1000, 1, labels=False, preds=False), frame(1000, 2, labels=False, preds=False), ["a"], None),
                {"mode": "events", "size": 250})
    assert r.summary["prediction"]["status"] == "not_assessable"
    assert r.summary["performance"]["status"] == "not_assessable"
    r = analyze(DriftFrames(frame(1000, 1, preds=False), frame(1000, 2, preds=False), ["a"], "Benign"), {"mode": "events", "size": 250})
    assert r.summary["performance"]["status"] == "not_assessable"


def test_small_windows_are_insufficient_not_judged():
    r = analyze(DriftFrames(frame(3000, 1), frame(150, 2, shift=3.0), ["a"], "Benign"), {"mode": "events", "size": 100})
    assert r.summary["feature"]["status"] == "insufficient_data" and r.events == [] or \
        all(e["drift_type"] != "feature" for e in r.events)
    assert all(w["features"]["a"]["severity"] == "insufficient_data" for w in r.windows)


def test_time_windows():
    r = analyze(DriftFrames(frame(2000, 1), frame(3000, 2), ["a"], "Benign"), {"mode": "time", "bucket": "hour"})
    assert len(r.windows) == 50 and r.windows[0]["n_events"] == 60
    with pytest.raises(ValueError):
        analyze(DriftFrames(frame(100, 1), frame(100, 2), ["a"], None), {"mode": "time", "bucket": "year"})


def test_adwin_rejects_unbounded_signals_and_finds_rate_change():
    with pytest.raises(ValueError):
        adwin_changes([0.0, 2.0, 1.0], 0.002)
    rng = np.random.default_rng(0)
    v = np.r_[rng.random(2000) < 0.05, rng.random(2000) < 0.3].astype(float)
    ch = adwin_changes(v, 0.002)
    assert ch and ch[0]["position"] >= 2000 and ch[0]["direction"] == "increase"
    assert adwin_changes((rng.random(4000) < 0.05).astype(float), 0.002) == []


def test_config_validation():
    with pytest.raises(DriftConfigError):
        DriftConfig.from_dict({"psi_moderate": 0.3, "psi_major": 0.2})
    with pytest.raises(DriftConfigError):
        DriftConfig.from_dict({"nonsense": 1})
    assert DriftConfig.from_dict({"alpha": 0.05}).alpha == 0.05


def test_controlled_experiment_separates_drift_types(tmp_path):
    from adaptive_ids.drift.experiment import run_experiment

    r = run_experiment(["none", "sudden", "concept"], repeats=1, seed=21, out_dir=tmp_path, n_reference=2500, n_current=3000)
    agg = r["aggregate"]
    assert all(v["false_alarms_total"] == 0 for k, v in agg["none"].items() if k != "mean_us_per_event")
    assert agg["sudden"]["feature_windows"]["detection_rate"] == 1.0
    assert agg["concept"]["feature_windows"]["detection_rate"] == 0.0
    assert agg["concept"]["adwin_error"]["detection_rate"] == 1.0
    assert (Path(r["run_dir"]) / "report.md").read_text().count("SYNTHETIC") >= 1
