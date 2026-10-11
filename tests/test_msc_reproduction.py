"""The MSc reproduction re-implements the notebook protocol; these tests pin the
behaviours the findings depend on, using a small synthetic NSL-KDD-shaped file."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from adaptive_ids.research import msc_reproduction as mr


def _fake_nsl_kdd(path, n=400, seed=0):
    rng = np.random.default_rng(seed)
    attack = rng.random(n) < 0.55
    cols = {}
    for i in range(41):
        if i in (1, 2, 3):  # protocol_type, service, flag are strings
            cols[i] = rng.choice(["tcp", "udp"], n) if i == 1 else rng.choice(["http", "ftp", "smtp"], n)
        elif i == 19:  # constant column, as num_outbound_cmds in NSL-KDD
            cols[i] = np.zeros(n)
        else:
            cols[i] = rng.normal(attack * (i % 3), 1.0)
    df = pd.DataFrame(cols)
    df[41] = np.where(attack, "neptune", "normal")
    df[42] = np.where(attack, rng.integers(15, 22, n), rng.integers(18, 22, n))  # difficulty level
    df.to_csv(path, header=False, index=False)
    return path


def test_load_raw_rejects_wrong_width(tmp_path):
    p = tmp_path / "bad.txt"
    pd.DataFrame(np.zeros((3, 10))).to_csv(p, header=False, index=False)
    with pytest.raises(ValueError, match="43"):
        mr.load_raw(p)


def test_labels_are_binary_and_normal_is_zero(tmp_path):
    df = mr._binary_labels(mr._notebook_columns(mr.load_raw(_fake_nsl_kdd(tmp_path / "t.txt"))))
    assert set(df["Label"].unique()) <= {0, 1}
    assert "Label" in df.columns and "41" not in df.columns


def test_dissertation_variant_keeps_difficulty_and_drops_constant(tmp_path):
    r = mr.run_variant("dissertation", _fake_nsl_kdd(tmp_path / "t.txt"))
    feats = r["split"]["features"]
    assert "42" in feats  # the notebook kept the difficulty column
    assert "19" not in feats  # constant column removed by variance filtering
    assert not {"1", "2", "3"} & set(feats)  # string columns are not numeric features
    s = r["split"]
    assert s["n_train"] + s["n_validation"] + s["n_test"] == 400
    assert s["n_test"] == 80


@pytest.mark.parametrize("variant", ["no_difficulty", "leak_free"])
def test_variants_without_difficulty(tmp_path, variant):
    r = mr.run_variant(variant, _fake_nsl_kdd(tmp_path / "t.txt"))
    assert "42" not in r["split"]["features"]
    m = r["models"]["Random_Forest"]
    assert 0.0 <= m["accuracy"] <= 1.0 and m["tp"] + m["fp"] + m["tn"] + m["fn"] == r["split"]["n_test"]


def test_leak_free_fits_on_training_rows_only(tmp_path, monkeypatch):
    seen = []
    orig = mr._FittedSteps.fit

    def spy(self, X, y):
        seen.append(len(X))
        return orig(self, X, y)

    monkeypatch.setattr(mr._FittedSteps, "fit", spy)
    r = mr.run_variant("leak_free", _fake_nsl_kdd(tmp_path / "t.txt"))
    assert seen == [r["split"]["n_train"]]
    seen.clear()
    mr.run_variant("dissertation", tmp_path / "t.txt")
    assert seen == [400]  # the notebook protocol fits on every row before splitting


def test_official_split_requires_train_file(tmp_path):
    with pytest.raises(ValueError, match="KDDTrain"):
        mr.run_variant("official_split", _fake_nsl_kdd(tmp_path / "t.txt"))
    r = mr.run_variant("official_split", tmp_path / "t.txt", _fake_nsl_kdd(tmp_path / "tr.txt", seed=1))
    assert r["split"]["n_train"] == 400 and r["split"]["n_test"] == 400


def test_run_reproduction_writes_labelled_result(tmp_path):
    test = _fake_nsl_kdd(tmp_path / "t.txt")
    out = mr.run_reproduction(test, out_dir=tmp_path / "runs")
    saved = json.loads((tmp_path / "runs").glob("msc-reproduction-*/result.json").__next__().read_text())
    assert saved["provenance"] == "baseline_reproduction"
    assert "not provided" in saved["note"]
    assert set(saved["variants"]) == {"dissertation", "no_difficulty", "leak_free"}
    assert len(saved["data"]["test_sha256"]) == 64
    rf_rows = [c for c in out["comparison_with_reported"] if c["model"] == "Random_Forest"]
    assert len(rf_rows) == 5 and all(c["reproduced"] is not None for c in rf_rows)


def test_prepare_named_csv(tmp_path):
    info = mr.prepare_named_csv(_fake_nsl_kdd(tmp_path / "t.txt"), tmp_path / "out" / "named.csv")
    df = pd.read_csv(tmp_path / "out" / "named.csv")
    assert info["rows"] == 400
    assert list(df.columns[:2]) == ["record_id", "row_order_time"]
    assert "difficulty" in df.columns and "label" in df.columns
