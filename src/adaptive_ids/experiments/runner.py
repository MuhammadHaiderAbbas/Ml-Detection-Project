"""Run a configured experiment end to end and write a reproducibility record.

Pipeline: import + validate dataset -> split -> fit preprocessor on the
training partition only -> load trusted model (or train an allow-listed
estimator) -> predict on validation and test partitions -> metrics ->
benchmark -> JSON result + Markdown report.

Validation metrics are for model selection; only test metrics are reported as
final results. The test partition is never used for fitting anything.
"""

from __future__ import annotations

import importlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..detection import ArtifactEntry, LoadedModel, Predictor, TrustedArtifactManifest, write_manifest
from ..evaluation import (
    benchmark_inference,
    chronological_split,
    classification_metrics,
    column_split,
    stratified_random_split,
)
from ..evaluation.splits import Split, _finalise
from ..ingestion import ROW_NUMBER_COLUMN, import_csv
from ..preprocessing import PreprocessingConfig, Preprocessor
from ..provenance import PROVENANCE_BANNERS, Provenance, sha256_file, sha256_json
from ..schema import FeatureSchema
from .config import TRAINABLE_ESTIMATORS, ConfigError, ExperimentConfig
from .environment import capture_environment
from .report import render_markdown_report

ATTACK_LABEL = "Attack"

# Keys accepted in reported_results.metrics, mapped to a lookup in the result.
REPORTABLE_METRICS = {
    "accuracy": ("accuracy",),
    "macro_precision": ("averages", "macro", "precision"),
    "macro_recall": ("averages", "macro", "recall"),
    "macro_f1": ("averages", "macro", "f1"),
    "weighted_precision": ("averages", "weighted", "precision"),
    "weighted_recall": ("averages", "weighted", "recall"),
    "weighted_f1": ("averages", "weighted", "f1"),
    "attack_precision": ("binary_attack_vs_benign", "precision"),
    "attack_recall": ("binary_attack_vs_benign", "recall_detection_rate"),
    "attack_f1": ("binary_attack_vs_benign", "f1"),
    "false_positive_rate": ("binary_attack_vs_benign", "false_positive_rate"),
    "false_negative_rate": ("binary_attack_vs_benign", "false_negative_rate"),
}


def _lookup(d: dict[str, Any], path: tuple[str, ...]) -> Any:
    for key in path:
        if not isinstance(d, dict) or key not in d:
            return None
        d = d[key]
    return d


def _resolve(base: Path, p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else base / path


def _make_split(cfg: ExperimentConfig, data: pd.DataFrame, schema: FeatureSchema, labels: pd.Series) -> Split:
    s = cfg.split
    method = s["method"]
    if method == "all_test":
        return _finalise([], [], np.arange(len(data)), "all_test", {})
    if method == "stratified_random":
        return stratified_random_split(
            labels, val_fraction=float(s.get("val_fraction", 0.0)),
            test_fraction=float(s["test_fraction"]), seed=int(s["seed"]),
        )
    if method == "chronological":
        col = s.get("timestamp_column") or schema.timestamp_column
        if not col or col not in data.columns:
            raise ConfigError("chronological split needs a timestamp column present in the data")
        return chronological_split(
            data, col, val_fraction=float(s.get("val_fraction", 0.0)),
            test_fraction=float(s["test_fraction"]), timestamp_format=s.get("timestamp_format"),
        )
    return column_split(data, s["column"])


def _build_estimator(name: str, params: dict[str, Any]) -> Any:
    module = importlib.import_module(TRAINABLE_ESTIMATORS[name])
    return getattr(module, name)(**params)


def _prepare_labels(cfg: ExperimentConfig, raw: pd.Series, schema: FeatureSchema) -> tuple[pd.Series, str | None]:
    ev = cfg.evaluation
    benign = ev.get("benign_label", schema.benign_label)
    y = raw.astype(str)
    if ev.get("binary_collapse"):
        if benign is None:
            raise ConfigError("binary_collapse requires a benign label")
        y = y.where(y == str(benign), ev.get("attack_label", ATTACK_LABEL))
    mapping = {str(k): str(v) for k, v in ev.get("label_mapping", {}).items()}
    if mapping:
        unmapped = sorted(set(y) - set(mapping))
        if unmapped:
            raise ConfigError(f"label_mapping does not cover dataset labels: {unmapped}")
        y = y.map(mapping)
        benign = mapping.get(str(benign), benign) if benign is not None else None
    return y, (str(benign) if benign is not None else None)


def run_experiment(config_path: str | Path, *, base_dir: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(config_path)
    cfg = ExperimentConfig.load(config_path)
    base = Path(base_dir) if base_dir else Path.cwd()
    started = datetime.now(timezone.utc)
    run_dir = _resolve(base, cfg.output_dir) / f"{cfg.experiment_id}-{started.strftime('%Y%m%dT%H%M%SZ')}"
    run_dir.mkdir(parents=True, exist_ok=False)
    timings: dict[str, float] = {}
    warnings_: list[str] = []
    limitations: list[str] = []

    schema_path = _resolve(base, cfg.schema_path)
    schema = FeatureSchema.load(schema_path)
    if schema.status != "verified":
        limitations.append(
            f"Feature schema {schema.schema_id} has status '{schema.status}' — it has not been "
            "confirmed against the original dissertation pipeline."
        )

    # 1. Import + validate --------------------------------------------------
    t0 = time.perf_counter()
    ds = cfg.dataset
    imported = import_csv(
        _resolve(base, ds["path"]), schema,
        dataset_name=ds["name"], dataset_version=ds["version"], provenance=cfg.provenance,
        column_mapping=ds.get("column_mapping"), expected_sha256=ds.get("expected_sha256"),
        duplicate_policy=ds.get("duplicate_policy", "keep"),
    )
    timings["import_s"] = time.perf_counter() - t0
    rec = imported.record
    (run_dir / "import_record.json").write_text(json.dumps(rec.to_dict(), indent=2), encoding="utf-8")
    imported.rejected.to_csv(run_dir / "rejected_rows.csv", index=False)
    warnings_.extend(rec.warnings)
    if not ds.get("expected_sha256"):
        limitations.append("dataset.expected_sha256 not set: the file hash is recorded but was not checked against a reference.")
    if rec.rejected_rows:
        limitations.append(
            f"{rec.rejected_rows} of {rec.total_rows} rows were rejected by validation and excluded "
            "(see rejected_rows.csv). The original study may have handled these rows differently."
        )
    data = imported.data
    if not schema.label_column or schema.label_column not in data.columns:
        raise ConfigError("evaluation requires a label column")
    y_all, benign = _prepare_labels(cfg, data[schema.label_column], schema)

    # 2. Split -------------------------------------------------------------
    split = _make_split(cfg, data, schema, y_all)
    (run_dir / "split_manifest.json").write_text(json.dumps(split.manifest, indent=2), encoding="utf-8")
    if split.manifest["method"] == "stratified_random":
        limitations.append(
            "Random (non-chronological) split: rows from the same time period appear in train and test, "
            "which can overestimate performance on future traffic."
        )
    train_df, val_df, test_df = (data.iloc[idx] for idx in (split.train, split.validation, split.test))
    y_train, y_val, y_test = (y_all.iloc[idx] for idx in (split.train, split.validation, split.test))
    if len(test_df) == 0:
        raise ConfigError("test partition is empty")

    # 3. Preprocessor: fitted on the training partition only ---------------
    pp = Preprocessor(schema, PreprocessingConfig(**cfg.preprocessing))
    if pp.requires_fit:
        if len(train_df) == 0:
            raise ConfigError("preprocessing requires fitting but the training partition is empty")
        pp.fit(train_df)
    pp.save(run_dir / "preprocessor.json")

    # 4. Model -------------------------------------------------------------
    t0 = time.perf_counter()
    m = cfg.model
    if m["mode"] == "trusted_artifact":
        loaded = TrustedArtifactManifest.load(_resolve(base, m["manifest"])).load_model(m["artifact_id"])
        warnings_.extend(loaded.warnings)
        if loaded.warnings:
            limitations.append(
                "The model artifact emitted warnings on load (often a scikit-learn version mismatch). "
                "Predictions may differ from the original environment; pin the original versions to confirm."
            )
        timings["model_load_s"] = time.perf_counter() - t0
    else:
        X_train = pp.transform(train_df)
        if len(X_train.rejected_index):
            warnings_.append(f"{len(X_train.rejected_index)} training rows dropped as non-finite after preprocessing")
        est = _build_estimator(m["estimator"], m.get("params", {}))
        est.fit(X_train.X, y_train.loc[X_train.X.index])
        timings["train_s"] = time.perf_counter() - t0
        model_path = run_dir / "model.joblib"
        import joblib

        joblib.dump(est, model_path)
        entry = ArtifactEntry(
            artifact_id=f"{cfg.experiment_id}-model",
            path=model_path.name,
            sha256=sha256_file(model_path),
            model_name=m.get("name", m["estimator"]),
            model_type=m["estimator"],
            provenance=cfg.provenance,
            trusted_by=f"adaptive-ids experiment runner ({cfg.experiment_id})",
            trusted_on=started.date().isoformat(),
            feature_schema_id=schema.schema_id,
            training_dataset=f"{ds['name']}@{ds['version']}",
        )
        write_manifest([entry], run_dir / "trusted_artifacts.json")
        loaded = LoadedModel(model=est, entry=entry, resolved_path=str(model_path))

    dec = cfg.decision
    predictor = Predictor(
        loaded.model, loaded.model_version, pp,
        positive_class=dec.get("positive_class"), threshold=dec.get("threshold"),
        calibrated=bool(dec.get("calibrated", False)),
    )
    if not predictor.calibrated and predictor.score_kind:
        limitations.append("Model scores are not calibrated probabilities.")

    # 5. Predict + evaluate ------------------------------------------------
    def evaluate(part: pd.DataFrame, y: pd.Series, name: str) -> dict[str, Any] | None:
        if len(part) == 0:
            return None
        t = time.perf_counter()
        preds = predictor.predict(part, event_ids=part[ROW_NUMBER_COLUMN].tolist())
        timings[f"predict_{name}_s"] = time.perf_counter() - t
        preds.insert(1, "true_label", y.to_numpy())
        if cfg.save_predictions:
            preds.to_csv(run_dir / f"predictions_{name}.csv", index=False)
        scored = preds["status"] == "ok"
        metrics = classification_metrics(
            preds.loc[scored, "true_label"], preds.loc[scored, "predicted_class"], benign_label=benign
        )
        metrics["n_rows"] = int(len(preds))
        metrics["n_rejected_at_inference"] = int((~scored).sum())
        return metrics

    t0 = time.perf_counter()
    val_metrics = evaluate(val_df, y_val, "validation")
    test_metrics = evaluate(test_df, y_test, "test")
    timings["evaluation_s"] = time.perf_counter() - t0

    bench_cfg = cfg.evaluation.get("benchmark", {})
    benchmark = None
    if bench_cfg.get("enabled", True):
        benchmark = benchmark_inference(
            predictor.predict, test_df,
            batch_size=int(bench_cfg.get("batch_size", 1000)), repeats=int(bench_cfg.get("repeats", 5)),
        )

    # 6. Compare against reported (e.g. dissertation) results ---------------
    comparison = []
    reported = cfg.reported_results.get("metrics", {})
    for key, value in reported.items():
        if key not in REPORTABLE_METRICS:
            warnings_.append(f"reported_results metric {key!r} is not recognised; skipped")
            continue
        got = _lookup(test_metrics or {}, REPORTABLE_METRICS[key])
        comparison.append({
            "metric": key, "reported": value, "reproduced": got,
            "difference": (got - value) if (got is not None and value is not None) else None,
        })
    if cfg.provenance == Provenance.BASELINE_REPRODUCTION.value and not reported:
        limitations.append("No original reported results were supplied, so reproduction could not be compared.")

    if cfg.provenance == Provenance.SYNTHETIC_DEMO.value:
        limitations.insert(0, PROVENANCE_BANNERS[Provenance.SYNTHETIC_DEMO])

    finished = datetime.now(timezone.utc)
    result = {
        "experiment_id": cfg.experiment_id,
        "objective": cfg.objective,
        "provenance": cfg.provenance,
        "provenance_banner": PROVENANCE_BANNERS[Provenance(cfg.provenance)],
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_s": (finished - started).total_seconds(),
        "timings_s": timings,
        "config": cfg.to_dict(),
        "config_sha256": sha256_file(config_path),
        "dataset": {
            "import_id": rec.import_id, "name": rec.dataset_name, "version": rec.dataset_version,
            "file_sha256": rec.file_sha256, "total_rows": rec.total_rows, "accepted_rows": rec.accepted_rows,
            "rejected_rows": rec.rejected_rows, "duplicate_rows": rec.duplicate_rows,
            "duplicates_dropped": rec.duplicates_dropped, "label_distribution": rec.label_distribution,
            "rejection_reason_counts": rec.rejection_reason_counts,
        },
        "schema": {"id": schema.schema_id, "hash": schema.schema_hash, "status": schema.status,
                   "n_features": len(schema.feature_names)},
        "split": split.manifest,
        "evaluated_label_distribution": {
            name: {str(k): int(v) for k, v in y.value_counts().items()}
            for name, y in (("train", y_train), ("validation", y_val), ("test", y_test))
        },
        "preprocessing": {"version_id": pp.version_id, "config": cfg.preprocessing or {}, "fitted_on": "train" if pp.is_fitted else None},
        "model": loaded.describe(),
        "decision": {"rule": predictor.decision_rule, "score_kind": predictor.score_kind},
        "metrics": {"validation": val_metrics, "test": test_metrics},
        "comparison_with_reported": {"source": cfg.reported_results.get("source"), "rows": comparison},
        "benchmark": benchmark,
        "environment": capture_environment(),
        "artifacts": sorted(p.name for p in run_dir.iterdir()),
        "warnings": warnings_,
        "limitations": limitations,
    }
    result["result_sha256"] = sha256_json({k: v for k, v in result.items() if k != "environment"})
    (run_dir / "result.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    (run_dir / "report.md").write_text(render_markdown_report(result), encoding="utf-8")
    result["run_dir"] = str(run_dir)
    return result
