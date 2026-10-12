import json
import shutil
from pathlib import Path

import joblib
import pytest
from conftest import REPO_ROOT

from adaptive_ids.detection import ArtifactEntry, write_manifest
from adaptive_ids.experiments import ConfigError, ExperimentConfig, run_experiment
from adaptive_ids.provenance import sha256_file
from adaptive_ids.research import write_synthetic_dataset


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "configs").mkdir()
    shutil.copytree(REPO_ROOT / "configs" / "schemas", tmp_path / "configs" / "schemas")
    write_synthetic_dataset(tmp_path / "data" / "flows_SYNTHETIC.csv", n_rows=1500, seed=1)
    return tmp_path


def _config(ws, **overrides):
    cfg = json.loads((REPO_ROOT / "configs/experiments/synthetic-demo.json").read_text())
    cfg["dataset"]["path"] = "data/flows_SYNTHETIC.csv"
    cfg["evaluation"]["benchmark"] = {"batch_size": 100, "repeats": 2}
    cfg["model"]["params"]["n_estimators"] = 20
    cfg.update(overrides)
    path = ws / f"exp-{len(list(ws.glob('exp-*.json')))}.json"
    path.write_text(json.dumps(cfg))
    return path


def test_synthetic_end_to_end(workspace):
    res = run_experiment(_config(workspace), base_dir=workspace)
    run = workspace / "experiments" / "runs"
    run_dir = next(run.iterdir())
    for name in ("result.json", "report.md", "import_record.json", "rejected_rows.csv",
                 "split_manifest.json", "preprocessor.json", "model.joblib", "trusted_artifacts.json",
                 "predictions_test.csv"):
        assert (run_dir / name).exists(), name
    assert res["dataset"]["rejected_rows"] == 6  # the injected malformed rows
    assert res["split"]["method"] == "chronological"
    assert res["metrics"]["test"]["n_scored"] > 0
    assert res["limitations"][0].startswith("SYNTHETIC DEMONSTRATION DATA")
    report = (run_dir / "report.md").read_text()
    assert "SYNTHETIC DEMONSTRATION DATA" in report
    assert res["environment"]["python"]


def test_baseline_reproduction_with_trusted_artifact(workspace):
    # Train a model in one run, then evaluate it as a "trusted artifact" in a second run.
    first = run_experiment(_config(workspace), base_dir=workspace)
    run_dir = workspace / "experiments" / "runs" / Path(first["run_dir"]).name
    cfg = _config(
        workspace,
        experiment_id="repro",
        provenance="synthetic_demo",
        split={"method": "chronological", "val_fraction": 0.15, "test_fraction": 0.25},
        model={"mode": "trusted_artifact", "manifest": str(run_dir / "trusted_artifacts.json"),
               "artifact_id": "synthetic-demo-rf-model"},
        reported_results={"source": "first run", "metrics": {
            "accuracy": first["metrics"]["test"]["accuracy"], "macro_f1": 0.5, "bogus": 1}},
    )
    second = run_experiment(cfg, base_dir=workspace)
    rows = {r["metric"]: r for r in second["comparison_with_reported"]["rows"]}
    assert rows["accuracy"]["difference"] == pytest.approx(0.0)  # same model + same split => same result
    assert rows["macro_f1"]["difference"] is not None
    assert any("bogus" in w for w in second["warnings"])


def test_tampered_model_stops_the_run(workspace, tmp_path):
    model_path = tmp_path / "evil.joblib"
    joblib.dump({"not": "a model"}, model_path)
    write_manifest([ArtifactEntry(artifact_id="x", path=str(model_path), sha256="1" * 64)], tmp_path / "t.json")
    cfg = _config(workspace, model={"mode": "trusted_artifact", "manifest": str(tmp_path / "t.json"), "artifact_id": "x"})
    from adaptive_ids.detection import ArtifactTrustError

    with pytest.raises(ArtifactTrustError):
        run_experiment(cfg, base_dir=workspace)


@pytest.mark.parametrize(
    "patch, msg",
    [
        ({"provenance": "original_dissertation"}, "cannot claim"),
        ({"provenance": "baseline_reproduction"}, "must evaluate the original"),
        ({"split": {"method": "stratified_random", "test_fraction": 0.2}}, "explicit seed"),
        ({"split": {"method": "all_test"}}, "cannot use the all_test"),
        ({"model": {"mode": "train", "estimator": "os.system"}}, "estimator must be one of"),
        ({"experiment_id": "../escape"}, "experiment_id"),
    ],
)
def test_config_validation(patch, msg):
    cfg = json.loads((REPO_ROOT / "configs/experiments/synthetic-demo.json").read_text())
    cfg.update(patch)
    with pytest.raises(ConfigError, match=msg):
        ExperimentConfig(**cfg)


def test_missing_dataset_fails_loudly(workspace):
    from adaptive_ids.ingestion import DatasetNotFoundError

    cfg = _config(workspace, dataset={"path": "data/missing.csv", "name": "x", "version": "1"})
    with pytest.raises(DatasetNotFoundError):
        run_experiment(cfg, base_dir=workspace)


def test_template_config_is_well_formed():
    data = json.loads((REPO_ROOT / "configs/experiments/baseline-reproduction.template.json").read_text())
    cfg = ExperimentConfig(**data)
    assert cfg.provenance == "baseline_reproduction" and cfg.model["mode"] == "trusted_artifact"


def test_sha_of_written_model_matches_manifest(workspace):
    res = run_experiment(_config(workspace), base_dir=workspace)
    manifest = json.loads((workspace / "experiments/runs" / Path(res["run_dir"]).name / "trusted_artifacts.json").read_text())
    entry = manifest["artifacts"][0]
    assert sha256_file(workspace / "experiments/runs" / Path(res["run_dir"]).name / entry["path"]) == entry["sha256"]
