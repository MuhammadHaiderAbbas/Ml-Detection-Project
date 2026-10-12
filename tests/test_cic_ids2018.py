"""CSE-CIC-IDS2018 loading and the chronological study, on small synthetic files with the real header.

The real day CSVs are 0.1-0.4 GB each and not in the repository; these files reproduce their
format and their known defects (repeated header rows, infinite values, corrupt 1970 timestamps).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from adaptive_ids.research.cic_ids2018 import LABEL, day_files, load_day, run_study, sample_day
from adaptive_ids.schema import FeatureSchema

REPO = Path(__file__).resolve().parents[1]
SCHEMA = FeatureSchema.load(REPO / "configs/schemas/cse-cic-ids2018.json")
FEATURES = SCHEMA.feature_names
COLUMNS = ["Dst Port", "Protocol", "Timestamp", *FEATURES[2:], "Label"]


def _write_day(path: Path, day: str, attacks: dict[str, int], n_benign: int, seed: int, *, defects: bool = True) -> None:
    rng = np.random.default_rng(seed)
    rows = []
    start = pd.Timestamp(day) + pd.Timedelta(hours=1)
    labels = [("Benign", n_benign)] + list(attacks.items())
    for k, (label, n) in enumerate(labels):
        X = rng.normal(0, 1, size=(n, len(FEATURES)))
        if label != "Benign":
            X[:, 3 + k] += 6  # each attack type separable on its own feature
        for i in range(n):
            ts = start + pd.Timedelta(seconds=int(rng.integers(0, 40_000)))
            row = dict(zip(FEATURES, X[i].round(4)))
            row["Timestamp"] = ts.strftime("%d/%m/%Y %H:%M:%S")
            row["Label"] = label
            rows.append(row)
    df = pd.DataFrame(rows)[COLUMNS]
    lines = df.astype(str).values.tolist()
    if defects:
        lines.insert(5, COLUMNS)  # repeated header row
        bad = list(lines[6]); bad[COLUMNS.index("Flow Byts/s")] = "Infinity"; lines[6] = bad
        old = list(lines[7]); old[COLUMNS.index("Timestamp")] = "05/01/1970 03:01:17"; lines[7] = old
    pd.DataFrame(lines, columns=COLUMNS).to_csv(path, index=False)


@pytest.fixture
def raw_dir(tmp_path):
    d = tmp_path / "raw"
    d.mkdir()
    _write_day(d / "Wednesday-14-02-2018.csv", "2018-02-14", {"FTP-BruteForce": 300}, 900, 1)
    _write_day(d / "Thursday-15-02-2018.csv", "2018-02-15", {"DoS attacks-GoldenEye": 300}, 900, 2)
    _write_day(d / "Friday-16-02-2018.csv", "2018-02-16", {"FTP-BruteForce": 200, "DoS attacks-Hulk": 300}, 900, 3)
    (d / "notes.txt").write_text("not a day file")
    return d


def test_schema_matches_the_real_header_layout():
    assert SCHEMA.schema_id == "cse-cic-ids2018@1.0.0" and SCHEMA.status == "verified"
    assert len(FEATURES) == 78 and "Timestamp" not in FEATURES and "Label" not in FEATURES
    assert SCHEMA.metadata["timestamp_format"] == "%d/%m/%Y %H:%M:%S"


def test_day_files_are_ordered_by_calendar_date_not_name(raw_dir):
    assert [p.name for p in day_files(raw_dir)] == [
        "Wednesday-14-02-2018.csv", "Thursday-15-02-2018.csv", "Friday-16-02-2018.csv"]


def test_load_day_drops_and_counts_known_defects(raw_dir):
    df, prof = load_day(raw_dir / "Wednesday-14-02-2018.csv", FEATURES)
    assert prof["repeated_header_rows"] == 1
    assert prof["rows_with_infinite_values"] == 1
    assert prof["rows_with_timestamp_on_another_day"] == 1
    assert prof["rows_in_file"] == 1201 and prof["rows_kept"] == 1198
    assert prof["possibly_truncated_at_excel_row_limit"] is False
    assert df["Timestamp"].is_monotonic_increasing and np.isfinite(df[FEATURES].to_numpy()).all()
    assert sum(prof["labels"].values()) == len(df)


def test_missing_columns_are_reported(tmp_path):
    p = tmp_path / "Wednesday-14-02-2018.csv"
    pd.DataFrame({"Label": ["Benign"]}).to_csv(p, index=False)
    with pytest.raises(ValueError, match="columns missing"):
        load_day(p, FEATURES)


def test_sampling_caps_each_class_and_is_seeded(raw_dir):
    df, _ = load_day(raw_dir / "Friday-16-02-2018.csv", FEATURES)
    a = sample_day(df, benign_cap=500, attack_cap=250, seed=4)
    b = sample_day(df, benign_cap=500, attack_cap=250, seed=4)
    counts = a[LABEL].value_counts().to_dict()
    assert counts["Benign"] == 500 and counts["DoS attacks-Hulk"] == 250 and counts["FTP-BruteForce"] <= 250
    assert a.equals(b) and a["Timestamp"].is_monotonic_increasing


def test_study_compares_strategies_on_unseen_days(raw_dir, tmp_path):
    r = run_study(raw_dir, out_dir=tmp_path / "runs", benign_cap=800, attack_cap=300, n_estimators=15)
    assert [d["day"] for d in r["per_day"]] == ["2018-02-15", "2018-02-16"]
    d15, d16 = r["per_day"]
    assert d15["novel_attack_types"] == ["DoS attacks-GoldenEye"]
    assert d16["novel_attack_types"] == ["DoS attacks-Hulk"]
    assert d16["by_attack_type"]["FTP-BruteForce"]["seen_in_training_before"] is True
    for d in r["per_day"]:
        assert set(d["metrics"]) == {"static", "retrain_always", "governed"}
        c = d["metrics"]["static"]["confusion"]
        assert sum(c.values()) == d["test_events"]
    # each synthetic attack type is separable on its own feature: a type seen in training is caught,
    # a type never seen before is not, whatever the strategy (adaptation needs labels first)
    ftp, hulk = d16["by_attack_type"]["FTP-BruteForce"], d16["by_attack_type"]["DoS attacks-Hulk"]
    assert min(ftp["recall_static"], ftp["recall_retrain_always"], ftp["recall_governed"]) > 0.9
    assert max(hulk["recall_static"], hulk["recall_retrain_always"], hulk["recall_governed"]) < 0.5
    assert [g["after_day"] for g in r["governance_log"]] == ["2018-02-15", "2018-02-16"]
    assert all(g["verdict"] in ("pass", "fail", "insufficient_evidence") for g in r["governance_log"])
    assert r["provenance"] == "controlled_experiment" and len(r["data"]["files"]) == 3
    run_dir = Path(r["run_dir"])
    assert json.loads((run_dir / "result.json").read_text())["per_day"][0]["day"] == "2018-02-15"
    report = (run_dir / "report.md").read_text()
    assert "Novel attack types" in report and "not analyst-confirmed" in report


def test_study_can_drop_features(raw_dir, tmp_path):
    r = run_study(raw_dir, out_dir=tmp_path / "runs", benign_cap=400, attack_cap=150, n_estimators=5,
                  drop_features=("Dst Port", "Protocol"))
    assert "Dst Port" not in r["settings"]["features"] and r["settings"]["dropped_features"] == ["Dst Port", "Protocol"]


def test_sample_is_written_in_the_original_format(raw_dir, tmp_path):
    from adaptive_ids.research.cic_ids2018 import write_sample

    out = tmp_path / "sample" / "Wednesday-14-02-2018.csv"
    res = write_sample(raw_dir / "Wednesday-14-02-2018.csv", out, benign_cap=100, attack_cap=50, seed=1)
    assert res["rows"] == 150
    back, prof = load_day(out, FEATURES)
    assert list(pd.read_csv(out, nrows=0).columns) == COLUMNS
    assert prof["rows_kept"] == 150 and back[LABEL].value_counts().to_dict() == {"Benign": 100, "FTP-BruteForce": 50}
