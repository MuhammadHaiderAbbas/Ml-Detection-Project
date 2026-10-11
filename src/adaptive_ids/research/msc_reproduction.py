"""Reproduction of the MSc notebook's supervised baseline (MSc_Project_Research.ipynb).

The notebook is never executed. Its preprocessing and model settings are
re-implemented here step by step (cell references in comments) so the run can
be repeated, and then varied one factor at a time:

* ``dissertation`` - the notebook's protocol as it actually ran: NSL-KDD
  KDDTest+ (the loader's fallback), numeric columns only, including column 42
  (NSL-KDD's per-record *difficulty level*), median imputation, variance
  filtering, mutual-information selection and standard scaling all fitted on
  the full dataset before a stratified random 70/10/20 split (seed 42).
* ``no_difficulty`` - identical, but without column 42.
* ``leak_free`` - split first; every fitted step fitted on the training
  partition only; no column 42.
* ``official_split`` - leak-free, trained on KDDTrain+ and tested on
  KDDTest+ (the dataset's published train/test protocol, whose test set
  contains attack types absent from training).

These runs retrain the models: the notebook's saved ``.pkl`` artifacts were
not provided, so this is a re-run of the original protocol, not an evaluation
of the original artifacts.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

# Values printed in the notebook's saved outputs (cell 25 / cell 42 "RESULTS").
REPORTED = {
    "Random_Forest": {"accuracy": 0.9960, "precision": 0.9946, "recall": 0.9984, "f1": 0.9965, "roc_auc": 1.0000},
    "XGBoost": {"accuracy": 0.9971, "precision": 0.9961, "recall": 0.9988, "f1": 0.9975, "roc_auc": 0.9999},
    "LightGBM": {"accuracy": 0.9967, "precision": 0.9957, "recall": 0.9984, "f1": 0.9971, "roc_auc": 1.0000},
}
REPORTED_SPLIT = {"train": 15780, "validation": 2255, "test": 4509, "n_features": 38, "attack_rate_test": 0.569}

NSL_KDD_COLUMNS = [
    "duration", "protocol_type", "service", "flag", "src_bytes", "dst_bytes", "land", "wrong_fragment", "urgent", "hot",
    "num_failed_logins", "logged_in", "num_compromised", "root_shell", "su_attempted", "num_root", "num_file_creations",
    "num_shells", "num_access_files", "num_outbound_cmds", "is_host_login", "is_guest_login", "count", "srv_count",
    "serror_rate", "srv_serror_rate", "rerror_rate", "srv_rerror_rate", "same_srv_rate", "diff_srv_rate",
    "srv_diff_host_rate", "dst_host_count", "dst_host_srv_count", "dst_host_same_srv_rate", "dst_host_diff_srv_rate",
    "dst_host_same_src_port_rate", "dst_host_srv_diff_host_rate", "dst_host_serror_rate", "dst_host_srv_serror_rate",
    "dst_host_rerror_rate", "dst_host_srv_rerror_rate", "label", "difficulty",
]


def load_raw(path: str | Path) -> pd.DataFrame:
    """Cell 8 fallback: ``pd.read_csv(..., header=None)`` -> integer column names."""
    df = pd.read_csv(path, header=None)
    if df.shape[1] != 43:
        raise ValueError(f"expected 43 NSL-KDD columns, found {df.shape[1]}")
    return df


def _notebook_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Cell 11, steps 1-2: names cast to str, '41' renamed to 'Label'; no column matches the
    identifier patterns ('ip', 'timestamp', ...) because NSL-KDD has numeric column names."""
    df = df.copy()
    df.columns = df.columns.astype(str)
    return df.rename(columns={"41": "Label"})


def _binary_labels(df: pd.DataFrame) -> pd.DataFrame:
    """Cell 11, step 5 (binary): BENIGN/NORMAL/... -> 0, anything else -> 1."""
    df = df.copy()
    normal = {"BENIGN", "NORMAL", "LEGITIMATE", "0", "NONE", "-"}
    df["Label"] = df["Label"].map(lambda x: 0 if str(x).strip().upper() in normal else 1)
    return df


def _numeric_feature_frame(df: pd.DataFrame, drop: list[str]) -> pd.DataFrame:
    cols = [c for c in df.columns if c != "Label" and c not in drop
            and df[c].dtype in (np.float64, np.float32, np.int64, np.int32)]
    return df[cols].astype("float64")


class _FittedSteps:
    """Median imputation -> VarianceThreshold(0) -> VarianceThreshold(1e-4) -> SelectKBest(MI, k=40) -> StandardScaler."""

    def __init__(self, k: int = 40, seed: int = 42):
        self.k, self.seed = k, seed

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> "_FittedSteps":
        from sklearn.feature_selection import SelectKBest, VarianceThreshold, mutual_info_classif
        from sklearn.preprocessing import StandardScaler

        self.medians = X.median()
        Xi = X.fillna(self.medians)
        self.vt0 = VarianceThreshold(0.0).fit(Xi)
        X0 = Xi.loc[:, self.vt0.get_support()]
        self.vt1 = VarianceThreshold(1e-4).fit(X0)
        X1 = X0.loc[:, self.vt1.get_support()]
        k = min(self.k, X1.shape[1])
        rng = np.random.RandomState(self.seed)
        self.selector = SelectKBest(lambda a, b: mutual_info_classif(a, b, random_state=rng), k=k)
        if len(X1) > 100_000:  # cell 11 samples 100k rows for selection on large data
            idx = np.random.default_rng(self.seed).choice(len(X1), 100_000, replace=False)
            self.selector.fit(X1.to_numpy()[idx], y[idx])
        else:
            self.selector.fit(X1.to_numpy(), y)
        self.features = list(X1.columns[self.selector.get_support()])
        self.scaler = StandardScaler().fit(X1[self.features].to_numpy())
        return self

    def transform(self, X: pd.DataFrame) -> np.ndarray:
        Xi = X.fillna(self.medians)
        return self.scaler.transform(Xi[self.features].to_numpy())


def _split(X: np.ndarray, y: np.ndarray, seed: int = 42):
    """Cell 11: stratified 80/20, then 12.5% of the remainder as validation (=> 70/10/20)."""
    from sklearn.model_selection import train_test_split

    idx = np.arange(len(y))
    tv, te = train_test_split(idx, test_size=0.2, random_state=seed, stratify=y)
    tr, va = train_test_split(tv, test_size=0.1 / 0.8, random_state=seed, stratify=y[tv])
    return tr, va, te


def _models() -> dict[str, Callable[[], Any]]:
    """Cell 18 settings."""
    from sklearn.ensemble import RandomForestClassifier

    out: dict[str, Callable[[], Any]] = {
        "Random_Forest": lambda: RandomForestClassifier(n_estimators=200, max_depth=20, min_samples_split=5,
                                                        class_weight="balanced", n_jobs=-1, random_state=42),
    }
    try:
        import xgboost as xgb

        out["XGBoost"] = lambda: xgb.XGBClassifier(n_estimators=200, max_depth=6, learning_rate=0.1, subsample=0.8,
                                                   colsample_bytree=0.8, scale_pos_weight=1, eval_metric="logloss",
                                                   n_jobs=-1, random_state=42, verbosity=0)
    except ImportError:
        pass
    try:
        import lightgbm as lgb

        out["LightGBM"] = lambda: lgb.LGBMClassifier(n_estimators=200, max_depth=6, learning_rate=0.1, num_leaves=31,
                                                     class_weight="balanced", n_jobs=-1, random_state=42, verbose=-1)
    except ImportError:
        pass
    return out


def _metrics(y: np.ndarray, pred: np.ndarray, proba: np.ndarray) -> dict[str, float]:
    from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score

    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    return {
        "accuracy": float(accuracy_score(y, pred)), "precision": float(precision_score(y, pred, zero_division=0)),
        "recall": float(recall_score(y, pred, zero_division=0)), "f1": float(f1_score(y, pred, zero_division=0)),
        "roc_auc": float(roc_auc_score(y, proba)), "false_positive_rate": float(fp / (fp + tn)) if fp + tn else None,
        "tp": int(tp), "fp": int(fp), "tn": int(tn), "fn": int(fn),
    }


def _fit_eval(Xtr, ytr, Xte, yte) -> dict[str, Any]:
    out = {}
    for name, make in _models().items():
        t0 = time.perf_counter()
        m = make().fit(Xtr, ytr)
        fit_s = time.perf_counter() - t0
        out[name] = {**_metrics(yte, m.predict(Xte), m.predict_proba(Xte)[:, 1]), "fit_seconds": fit_s}
    return out


def run_variant(variant: str, test_path: Path, train_path: Path | None = None) -> dict[str, Any]:
    raw = _binary_labels(_notebook_columns(load_raw(test_path)))
    y_all = raw["Label"].to_numpy()
    if variant in ("dissertation", "no_difficulty"):
        drop = [] if variant == "dissertation" else ["42"]
        X = _numeric_feature_frame(raw, drop)
        steps = _FittedSteps().fit(X, y_all)  # fitted on ALL rows, as in the notebook
        Xs = steps.transform(X)
        tr, va, te = _split(Xs, y_all)
        res = _fit_eval(Xs[tr], y_all[tr], Xs[te], y_all[te])
        info = {"n_train": len(tr), "n_validation": len(va), "n_test": len(te), "features": steps.features,
                "attack_rate_test": float(y_all[te].mean())}
    elif variant == "leak_free":
        X = _numeric_feature_frame(raw, ["42"])
        tr, va, te = _split(X.to_numpy(), y_all)
        steps = _FittedSteps().fit(X.iloc[tr], y_all[tr])
        res = _fit_eval(steps.transform(X.iloc[tr]), y_all[tr], steps.transform(X.iloc[te]), y_all[te])
        info = {"n_train": len(tr), "n_validation": len(va), "n_test": len(te), "features": steps.features,
                "attack_rate_test": float(y_all[te].mean())}
    elif variant == "official_split":
        if train_path is None:
            raise ValueError("official_split needs KDDTrain+")
        tr_raw = _binary_labels(_notebook_columns(load_raw(train_path)))
        Xtr_df = _numeric_feature_frame(tr_raw, ["42"])
        Xte_df = _numeric_feature_frame(raw, ["42"])[Xtr_df.columns]
        steps = _FittedSteps().fit(Xtr_df, tr_raw["Label"].to_numpy())
        res = _fit_eval(steps.transform(Xtr_df), tr_raw["Label"].to_numpy(), steps.transform(Xte_df), y_all)
        info = {"n_train": len(Xtr_df), "n_validation": 0, "n_test": len(Xte_df), "features": steps.features,
                "attack_rate_test": float(y_all.mean())}
    else:
        raise ValueError(f"unknown variant {variant!r}")
    return {"variant": variant, "split": info, "models": res}


def run_reproduction(test_path: str | Path, train_path: str | Path | None = None, out_dir: str | Path = "experiments/runs") -> dict[str, Any]:
    from ..experiments.environment import capture_environment
    from ..provenance import sha256_file

    test_path = Path(test_path)
    train_path = Path(train_path) if train_path else None
    started = datetime.now(timezone.utc)
    variants = ["dissertation", "no_difficulty", "leak_free"] + (["official_split"] if train_path else [])
    results = {v: run_variant(v, test_path, train_path) for v in variants}
    d = results["dissertation"]
    comparison = []
    for model, rep in REPORTED.items():
        got = d["models"].get(model)
        for k, v in rep.items():
            comparison.append({"model": model, "metric": k, "reported": v,
                               "reproduced": None if got is None else round(got[k], 4),
                               "difference": None if got is None else round(got[k] - v, 4)})
    out = {
        "experiment": "msc-baseline-reproduction",
        "provenance": "baseline_reproduction",
        "note": "Re-run of the notebook's protocol with retrained models (original .pkl artifacts not provided).",
        "started_at": started.isoformat(),
        "data": {"test_file": test_path.name, "test_sha256": sha256_file(test_path),
                 "train_file": train_path.name if train_path else None,
                 "train_sha256": sha256_file(train_path) if train_path else None},
        "reported_split": REPORTED_SPLIT, "comparison_with_reported": comparison, "variants": results,
        "environment": capture_environment(),
    }
    run_dir = Path(out_dir) / f"msc-reproduction-{started.strftime('%Y%m%dT%H%M%SZ')}"
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "result.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    out["run_dir"] = str(run_dir)
    return out


def prepare_named_csv(src: str | Path, dest: str | Path) -> dict[str, Any]:
    """Write an NSL-KDD file as a headed CSV usable by the platform's importer.

    Adds a synthetic event timestamp (row order, 1 s apart, labelled as such in
    the column name) because NSL-KDD has no time information.
    """
    df = load_raw(src)
    df.columns = NSL_KDD_COLUMNS
    df.insert(0, "record_id", [f"r{i:06d}" for i in range(len(df))])
    df.insert(1, "row_order_time", pd.date_range("2000-01-01", periods=len(df), freq="s").strftime("%Y-%m-%d %H:%M:%S"))
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(dest, index=False)
    return {"rows": len(df), "dest": str(dest)}
