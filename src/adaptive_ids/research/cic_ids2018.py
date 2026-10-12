"""CSE-CIC-IDS2018: loading, profiling and a chronological study of static vs adaptive models.

Data: the public "Processed Traffic Data for ML Algorithms" CSVs (CICFlowMeter output, one file
per capture day) from the dataset's official bucket. Each day contains benign traffic plus the
attacks run that day, so moving forward in time also means meeting attack types never seen
before. That makes it a hard, honest test of whether a model keeps working as traffic changes.

The study (``run_study``), every number of which is measured, never assumed:

* **static**: one model trained on the first day, never updated;
* **retrain_always**: before each test day, a model retrained on every earlier labelled day;
* **governed**: Adaptive IDS's own rule. After each day's labels arrive, a candidate is trained
  and compared with the active model on a held-out part of that day using the platform's
  evaluation protocol (paired bootstrap, non-inferiority margins). It replaces the active model
  only if the verdict is ``pass``.

All strategies are tested on the same events of each later day, which no model has trained on.
Drift is measured with the platform's own statistics: feature drift of each day's benign traffic
against the first day's, and ADWIN on the static model's error stream.

Known properties of this dataset that the report states: the processed CSVs have no IP
addresses; a few rows repeat the header; some values are infinite; labels are the dataset's own
(not analyst-confirmed), and published analyses report labelling problems on some days.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

LABEL, TIMESTAMP = "Label", "Timestamp"
BENIGN = "Benign"
TIMESTAMP_FORMAT = "%d/%m/%Y %H:%M:%S"
_DAY_RE = re.compile(r"(\d{2})-(\d{2})-(\d{4})")
SKIPPED_DAYS_NOTE = ("Tuesday 20-02-2018 (4 GB; the only processed file with IP and flow-ID columns) is not "
                     "included in this study.")


def day_files(raw_dir: str | Path) -> list[Path]:
    """The day CSVs in ``raw_dir``, in calendar order (file names carry dd-mm-yyyy)."""
    files = []
    for p in Path(raw_dir).glob("*.csv"):
        m = _DAY_RE.search(p.name)
        if m:
            d, mth, y = m.groups()
            files.append((f"{y}-{mth}-{d}", p))
    if not files:
        raise FileNotFoundError(f"no CSE-CIC-IDS2018 day files (named like Wednesday-14-02-2018.csv) in {raw_dir}")
    return [p for _, p in sorted(files)]


def day_of(path: Path) -> str:
    d, m, y = _DAY_RE.search(path.name).groups()
    return f"{y}-{m}-{d}"


def load_day(path: str | Path, features: list[str]) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Read one day; drop repeated header rows and rows with missing or infinite feature values.

    Returns the clean frame (features as float64, ``Label``, parsed ``Timestamp``) sorted by time,
    and a profile of what was read and dropped.
    """
    path = Path(path)
    header = pd.read_csv(path, nrows=0).columns
    missing = [c for c in [*features, LABEL, TIMESTAMP] if c not in header]
    if missing:
        raise ValueError(f"{path.name}: columns missing from the file: {missing}")
    counts = {"rows": 0, "header": 0, "inf": 0, "nan": 0, "ts": 0, "ts_other_day": 0}
    file_day = pd.Timestamp(day_of(path))
    parts = []
    # Read as text in chunks (repeated header rows make pandas' type inference unreliable).
    for raw in pd.read_csv(path, dtype=str, keep_default_na=False, usecols=[*features, LABEL, TIMESTAMP],
                           chunksize=200_000):
        counts["rows"] += len(raw)
        header_rows = raw[LABEL].eq(LABEL)
        counts["header"] += int(header_rows.sum())
        raw = raw.loc[~header_rows]
        X = raw[features].apply(pd.to_numeric, errors="coerce")
        inf_rows = np.isinf(X.to_numpy()).any(axis=1)
        nan_rows = X.isna().any(axis=1).to_numpy()
        ts = pd.to_datetime(raw[TIMESTAMP], format=TIMESTAMP_FORMAT, errors="coerce")
        unparsed = ts.isna().to_numpy()
        # Some rows carry corrupt timestamps (e.g. 1970-01-05); they cannot be placed in time.
        other_day = ~unparsed & (ts.dt.normalize() != file_day).to_numpy()
        bad_ts = unparsed | other_day
        counts["ts_other_day"] += int((other_day & ~inf_rows & ~nan_rows).sum())
        counts["inf"] += int(inf_rows.sum())
        counts["nan"] += int((nan_rows & ~inf_rows).sum())
        counts["ts"] += int((unparsed & ~inf_rows & ~nan_rows).sum())
        keep = ~(inf_rows | nan_rows | bad_ts)
        part = X.loc[keep].astype("float64")
        part[LABEL] = raw.loc[keep, LABEL].to_numpy()
        part[TIMESTAMP] = ts[keep].to_numpy()
        parts.append(part)
    df = pd.concat(parts, ignore_index=True)
    df = df.sort_values(TIMESTAMP, kind="stable").reset_index(drop=True)
    labels = df[LABEL].value_counts().to_dict()
    profile = {
        "file": path.name, "day": day_of(path), "rows_in_file": counts["rows"],
        "repeated_header_rows": counts["header"], "rows_with_infinite_values": counts["inf"],
        "rows_with_missing_values": counts["nan"], "rows_with_bad_timestamp": counts["ts"],
        "rows_with_timestamp_on_another_day": counts["ts_other_day"], "rows_kept": int(len(df)),
        # 1,048,575 data rows + a header = Excel's row limit: the file was very likely cut off there.
        "possibly_truncated_at_excel_row_limit": counts["rows"] == 1_048_575,
        "exact_duplicate_rows": int(df.duplicated().sum()),
        "labels": {str(k): int(v) for k, v in sorted(labels.items(), key=lambda kv: -kv[1])},
        "first_timestamp": str(df[TIMESTAMP].min()) if len(df) else None,
        "last_timestamp": str(df[TIMESTAMP].max()) if len(df) else None,
    }
    return df, profile


def sample_day(df: pd.DataFrame, *, benign_cap: int, attack_cap: int, seed: int) -> pd.DataFrame:
    """Seeded cap per class (all rows of a class below its cap are kept), kept in time order."""
    parts = []
    for i, (label, g) in enumerate(sorted(df.groupby(LABEL), key=lambda kv: kv[0])):
        cap = benign_cap if label == BENIGN else attack_cap
        parts.append(g if len(g) <= cap else g.sample(n=cap, random_state=seed + i))
    return pd.concat(parts).sort_values(TIMESTAMP, kind="stable").reset_index(drop=True)


# --------------------------------------------------------------------------- study


def _forest(seed: int, n_estimators: int) -> Any:
    from sklearn.ensemble import RandomForestClassifier

    return RandomForestClassifier(n_estimators=n_estimators, random_state=seed, n_jobs=-1, min_samples_leaf=1)


def _fit(X: np.ndarray, y_attack: np.ndarray, seed: int, n_estimators: int) -> tuple[Any, float]:
    t0 = time.perf_counter()
    model = _forest(seed, n_estimators).fit(X, y_attack)
    return model, time.perf_counter() - t0


def _rates(truth: np.ndarray, flag: np.ndarray) -> dict[str, Any]:
    tp = int(np.sum(flag & truth)); fp = int(np.sum(flag & ~truth))
    fn = int(np.sum(~flag & truth)); tn = int(np.sum(~flag & ~truth))
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    f1 = (2 * prec * rec / (prec + rec)) if prec is not None and rec is not None and prec + rec else None
    return {"precision": prec, "recall": rec, "f1": f1, "false_positive_rate": fp / (fp + tn) if fp + tn else None,
            "confusion": {"tp": tp, "fp": fp, "tn": tn, "fn": fn}}


def write_sample(src: str | Path, dest: str | Path, *, benign_cap: int, attack_cap: int, seed: int = 0,
                 features: list[str] | None = None) -> dict[str, Any]:
    """Write a seeded per-class sample of one day in the dataset's own CSV format (for the importer)."""
    from ..schema import FeatureSchema

    if features is None:
        repo = Path(__file__).resolve().parents[3]
        features = FeatureSchema.load(repo / "configs/schemas/cse-cic-ids2018.json").feature_names
    df, profile = load_day(src, features)
    s = sample_day(df, benign_cap=benign_cap, attack_cap=attack_cap, seed=seed)
    out = s[features].copy()
    out.insert(2, TIMESTAMP, s[TIMESTAMP].dt.strftime(TIMESTAMP_FORMAT))
    out[LABEL] = s[LABEL]
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(dest, index=False)
    return {"source": profile, "rows": int(len(out)), "labels": out[LABEL].value_counts().to_dict(), "dest": str(dest)}


def _cap_rows(df: pd.DataFrame, cap: int, seed: int) -> pd.DataFrame:
    return df if len(df) <= cap else df.sample(n=cap, random_state=seed).sort_values(TIMESTAMP, kind="stable")


def run_study(raw_dir: str | Path, *, out_dir: str | Path = "experiments/runs", schema_path: str | Path | None = None,
              protocol_path: str | Path | None = None, benign_cap: int = 60_000, attack_cap: int = 20_000,
              holdout_fraction: float = 0.3, max_train_rows: int = 400_000, n_estimators: int = 100,
              seed: int = 0, drop_features: tuple[str, ...] = ()) -> dict[str, Any]:
    from ..drift.config import DriftConfig
    from ..drift.stats import bonferroni, classify, numeric_drift
    from ..drift.streaming import adwin_changes
    from ..experiments.environment import capture_environment, peak_memory_mb
    from ..governance import compare_models, load_protocol
    from ..governance.protocol import EvaluationProtocol
    from ..provenance import sha256_file
    from ..schema import FeatureSchema

    repo = Path(__file__).resolve().parents[3]
    schema = FeatureSchema.load(schema_path or repo / "configs/schemas/cse-cic-ids2018.json")
    features = [f for f in schema.feature_names if f not in drop_features]
    protocol = load_protocol(protocol_path) if protocol_path else (
        load_protocol(repo / "configs/evaluation-protocol.json")
        if (repo / "configs/evaluation-protocol.json").is_file() else EvaluationProtocol())
    drift_cfg = DriftConfig()
    started = datetime.now(timezone.utc)
    t_start = time.perf_counter()

    files = day_files(raw_dir)
    days, profiles, hashes = [], [], {}
    for i, p in enumerate(files):
        df, prof = load_day(p, features)
        s = sample_day(df, benign_cap=benign_cap, attack_cap=attack_cap, seed=seed + 100 * i)
        prof["sampled"] = {"rows": int(len(s)), "labels": {str(k): int(v) for k, v in s[LABEL].value_counts().items()}}
        profiles.append(prof)
        hashes[p.name] = sha256_file(p)
        days.append((day_of(p), s))
        del df

    # Each day: a training part (earlier in the day) and a held-out part used for the governance gate.
    # Test events of day k are the WHOLE sampled day k; models used on day k never saw any of day k.
    def split(s: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        rng = np.random.default_rng(seed)
        mask = rng.random(len(s)) < holdout_fraction
        return s.loc[~mask], s.loc[mask]

    def xy(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        return df[features].to_numpy(dtype="float64"), (df[LABEL].to_numpy() != BENIGN)

    def train_on(frames: list[pd.DataFrame], tag: int) -> tuple[Any, float, int]:
        data = _cap_rows(pd.concat(frames), max_train_rows, seed + tag)
        X, y = xy(data)
        if y.all() or not y.any():
            raise ValueError("training data needs both benign and attack rows")
        m, secs = _fit(X, y, seed, n_estimators)
        return m, secs, len(data)

    splits = [split(s) for _, s in days]
    static, t_static, n_static = train_on([days[0][1]], 0)
    active, active_from = static, days[0][0]
    seen_types = {lbl for lbl in days[0][1][LABEL].unique() if lbl != BENIGN}

    per_day: list[dict[str, Any]] = []
    error_stream: list[int] = []
    boundaries: list[tuple[str, int]] = []
    ref_benign = days[0][1].loc[days[0][1][LABEL] == BENIGN, features]
    training_log = [{"after_day": days[0][0], "strategy": "static", "train_rows": n_static, "fit_seconds": round(t_static, 2)}]
    gate_log: list[dict[str, Any]] = []

    for k in range(1, len(days)):
        day, test = days[k]
        X, truth = xy(test)
        retrain, t_rt, n_rt = train_on([d for _, d in days[:k]], k)
        training_log.append({"after_day": days[k - 1][0], "strategy": "retrain_always", "train_rows": n_rt,
                             "fit_seconds": round(t_rt, 2)})
        models = {"static": static, "retrain_always": retrain, "governed": active}
        t0 = time.perf_counter()
        flags = {name: m.predict(X).astype(bool) for name, m in models.items()}
        predict_seconds = (time.perf_counter() - t0) / len(models)

        types = sorted({lbl for lbl in test[LABEL].unique() if lbl != BENIGN})
        by_type: dict[str, Any] = {}
        for t in types:
            m = test[LABEL].to_numpy() == t
            by_type[t] = {"events": int(m.sum()), "seen_in_training_before": t in seen_types,
                          **{f"recall_{name}": float(f[m].mean()) for name, f in flags.items()}}
        comparisons = {}
        for name in ("retrain_always", "governed"):
            c = compare_models(truth, flags[name], np.ones_like(truth), protocol, flags["static"], np.ones_like(truth))
            comparisons[f"{name}_vs_static"] = {"differences": c.differences, "verdict_under_protocol": c.verdict}

        # feature drift of this day's benign traffic vs the first day's
        cur_benign = test.loc[test[LABEL] == BENIGN, features]
        fd = {f: numeric_drift(ref_benign[f], cur_benign[f], drift_cfg) for f in features}
        p_adj = bonferroni([fd[f]["ks_p"] for f in features])
        severities = [classify(fd[f]["psi"], p, fd[f]["n_ref"], fd[f]["n_cur"], drift_cfg) for f, p in zip(features, p_adj)]
        top = sorted(((f, fd[f]["psi"]) for f in features if fd[f]["psi"] is not None), key=lambda kv: -kv[1])[:5]

        boundaries.append((day, len(error_stream)))
        error_stream.extend((flags["static"] != truth).astype(int).tolist())
        per_day.append({
            "day": day, "test_events": int(len(test)), "attack_events": int(truth.sum()), "attack_types": types,
            "novel_attack_types": [t for t in types if t not in seen_types],
            "metrics": {name: _rates(truth, f) for name, f in flags.items()},
            "governed_model_trained_through": active_from,
            "by_attack_type": by_type, "paired_differences": comparisons,
            "benign_feature_drift": {"major": severities.count("major"), "moderate": severities.count("moderate"),
                                     "none": severities.count("none"), "features": len(features),
                                     "top_psi": [{"feature": f, "psi": round(v, 3)} for f, v in top]},
            "predict_seconds_per_model": round(predict_seconds, 3),
        })

        # labels for day k arrive: governed candidate trained on earlier days + this day's training part,
        # gated against the active model on this day's held-out part.
        train_k, hold_k = splits[k]
        cand, t_c, n_c = train_on([d for _, d in days[:k]] + [train_k], 1000 + k)
        Xh, th = xy(hold_k)
        gate = compare_models(th, cand.predict(Xh).astype(bool), np.ones_like(th), protocol,
                              active.predict(Xh).astype(bool), np.ones_like(th))
        promoted = gate.verdict == "pass"
        gate_log.append({"after_day": day, "holdout_events": int(len(hold_k)), "verdict": gate.verdict,
                         "failed_gates": [g["id"] for g in gate.gates if g["passed"] is False],
                         "promoted": promoted, "candidate_train_rows": n_c, "fit_seconds": round(t_c, 2)})
        if promoted:
            active, active_from = cand, day
        seen_types |= {lbl for lbl in test[LABEL].unique() if lbl != BENIGN}

    changes = adwin_changes(error_stream, drift_cfg.adwin_delta, max_events=200)
    detection = []
    for i, (day, start) in enumerate(boundaries):
        end = boundaries[i + 1][1] if i + 1 < len(boundaries) else len(error_stream)
        hits = [c for c in changes if start <= c["position"] < end]
        detection.append({"day": day, "first_alarm_events_after_day_start": hits[0]["position"] - start if hits else None,
                          "alarms": len(hits), "direction_of_first": hits[0]["direction"] if hits else None,
                          "static_error_rate": round(float(np.mean(error_stream[start:end])), 4)})

    out = {
        "experiment": "cic-ids2018-chronological",
        "provenance": "controlled_experiment",
        "dataset": "CSE-CIC-IDS2018, processed CICFlowMeter CSVs (public)",
        "started_at": started.isoformat(timespec="seconds"),
        "settings": {"benign_cap_per_day": benign_cap, "attack_cap_per_class_per_day": attack_cap,
                     "holdout_fraction_for_gate": holdout_fraction, "max_train_rows": max_train_rows,
                     "model": f"RandomForestClassifier(n_estimators={n_estimators}), binary attack vs benign",
                     "seed": seed, "features": features, "dropped_features": list(drop_features),
                     "protocol": protocol.to_dict() if hasattr(protocol, "to_dict") else None,
                     "drift_config": drift_cfg.to_dict()},
        "data": {"files": hashes, "profiles": profiles, "not_included": SKIPPED_DAYS_NOTE},
        "per_day": per_day, "governance_log": gate_log, "training_log": training_log,
        "static_error_stream_adwin": {"delta": drift_cfg.adwin_delta, "per_day": detection},
        "runtime": {"total_seconds": round(time.perf_counter() - t_start, 1), "peak_memory_mb": peak_memory_mb()},
        "environment": capture_environment(),
    }
    run_dir = Path(out_dir) / f"cic-ids2018-chronological-{started.strftime('%Y%m%dT%H%M%SZ')}"
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "result.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    (run_dir / "report.md").write_text(render_report(out), encoding="utf-8")
    out["run_dir"] = str(run_dir)
    return out


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:.1f} %"


def _pp(d: dict[str, Any], m: str) -> str:
    x = d.get(m) or {}
    if x.get("difference") is None:
        return "—"
    return f"{x['difference'] * 100:+.1f} pp [{x['ci_low'] * 100:+.1f}, {x['ci_high'] * 100:+.1f}]"


def render_report(r: dict[str, Any]) -> str:
    s = r["settings"]
    lines = [
        "# CSE-CIC-IDS2018: static vs adaptive models over time",
        "",
        f"Provenance: **{r['provenance']}**. Run started {r['started_at']}. Public dataset; labels are the dataset's own, "
        "not analyst-confirmed.",
        "",
        f"Model: {s['model']}, seed {s['seed']}. Per day, up to {s['benign_cap_per_day']:,} benign rows and "
        f"{s['attack_cap_per_class_per_day']:,} rows per attack class were sampled (seeded). Training sets are capped at "
        f"{s['max_train_rows']:,} rows. {r['data']['not_included']}",
        "",
        "## Data",
        "",
        "| Day | Rows in file | Header rows | Infinite | Kept | Sampled | Labels in sample |",
        "|---|---|---|---|---|---|---|",
    ]
    for p in r["data"]["profiles"]:
        labels = ", ".join(f"{k} {v:,}" for k, v in p["sampled"]["labels"].items())
        lines.append(f"| {p['day']} | {p['rows_in_file']:,} | {p['repeated_header_rows']:,} | "
                     f"{p['rows_with_infinite_values']:,} | {p['rows_kept']:,} | {p['sampled']['rows']:,} | {labels} |")
    lines += ["", "## Results per test day (attack vs benign)", "",
              "| Day | Novel attack types | Static recall / FPR | Retrain-always recall / FPR | Governed recall / FPR | Governed model trained through |",
              "|---|---|---|---|---|---|"]
    for d in r["per_day"]:
        m = d["metrics"]
        cell = lambda k: f"{_pct(m[k]['recall'])} / {_pct(m[k]['false_positive_rate'])}"  # noqa: E731
        lines.append(f"| {d['day']} | {', '.join(d['novel_attack_types']) or '—'} | {cell('static')} | "
                     f"{cell('retrain_always')} | {cell('governed')} | {d['governed_model_trained_through']} |")
    lines += ["", "## Paired differences against the static model (95 % bootstrap CI)", "",
              "| Day | Retrain-always: recall | Retrain-always: FPR | Governed: recall | Governed: FPR |", "|---|---|---|---|---|"]
    for d in r["per_day"]:
        ra = d["paired_differences"]["retrain_always_vs_static"]["differences"]
        gv = d["paired_differences"]["governed_vs_static"]["differences"]
        lines.append(f"| {d['day']} | {_pp(ra, 'attack_recall')} | {_pp(ra, 'false_positive_rate')} | "
                     f"{_pp(gv, 'attack_recall')} | {_pp(gv, 'false_positive_rate')} |")
    lines += ["", "## Recall by attack type", "", "| Day | Attack type | Events | Seen before | Static | Retrain-always | Governed |",
              "|---|---|---|---|---|---|---|"]
    for d in r["per_day"]:
        for t, v in d["by_attack_type"].items():
            lines.append(f"| {d['day']} | {t} | {v['events']:,} | {'yes' if v['seen_in_training_before'] else 'no'} | "
                         f"{_pct(v['recall_static'])} | {_pct(v['recall_retrain_always'])} | {_pct(v['recall_governed'])} |")
    lines += ["", "## Governance decisions", "", "| After labels of | Verdict | Failed gates | Promoted |", "|---|---|---|---|"]
    for g in r["governance_log"]:
        lines.append(f"| {g['after_day']} | {g['verdict']} | {', '.join(g['failed_gates']) or '—'} | {'yes' if g['promoted'] else 'no'} |")
    lines += ["", "## Drift", "", "| Day | Benign features with major / moderate drift (of all) | Top PSI | ADWIN alarms on static errors | First alarm (events into the day) |",
              "|---|---|---|---|---|"]
    det = {x["day"]: x for x in r["static_error_stream_adwin"]["per_day"]}
    for d in r["per_day"]:
        bd = d["benign_feature_drift"]; a = det[d["day"]]
        top = ", ".join(f"{t['feature']} {t['psi']}" for t in bd["top_psi"][:3])
        lines.append(f"| {d['day']} | {bd['major']} / {bd['moderate']} (of {bd['features']}) | {top} | {a['alarms']} | "
                     f"{a['first_alarm_events_after_day_start'] if a['first_alarm_events_after_day_start'] is not None else '—'} |")
    rt = r["runtime"]
    lines += ["", f"Runtime: {rt['total_seconds']:,} s in total; peak memory {rt['peak_memory_mb']:,} MB.", ""]
    return "\n".join(lines)
