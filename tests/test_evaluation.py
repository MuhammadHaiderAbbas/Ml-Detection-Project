import numpy as np
import pandas as pd
import pytest

from adaptive_ids.evaluation import (
    benchmark_inference,
    chronological_split,
    classification_metrics,
    column_split,
    stratified_random_split,
)


def test_metrics_known_values():
    y_true = ["Benign"] * 6 + ["DoS"] * 4
    y_pred = ["Benign"] * 5 + ["DoS"] + ["DoS"] * 3 + ["Benign"]
    m = classification_metrics(y_true, y_pred, benign_label="Benign")
    assert m["accuracy"] == pytest.approx(0.8)
    assert m["confusion_matrix"]["rows_true_cols_pred"] == [[5, 1], [1, 3]]
    b = m["binary_attack_vs_benign"]
    assert (b["tp"], b["tn"], b["fp"], b["fn"]) == (3, 5, 1, 1)
    assert b["false_positive_rate"] == pytest.approx(1 / 6)
    assert b["false_negative_rate"] == pytest.approx(1 / 4)
    assert b["precision"] == pytest.approx(0.75)
    assert m["per_class"]["DoS"]["recall"] == pytest.approx(0.75)


def test_multiclass_binary_collapse_view():
    y_true = ["Benign", "DoS", "Scan", "Scan"]
    y_pred = ["Benign", "Scan", "Scan", "Benign"]
    b = classification_metrics(y_true, y_pred, benign_label="Benign")["binary_attack_vs_benign"]
    # DoS predicted as Scan is still a detected attack in the binary view
    assert (b["tp"], b["fn"]) == (2, 1)


def test_empty_metrics_rejected():
    with pytest.raises(ValueError):
        classification_metrics([], [])


def test_chronological_split_respects_time():
    ts = pd.date_range("2026-01-01", periods=100, freq="min")
    df = pd.DataFrame({"Timestamp": ts[::-1].astype(str)})  # file order reversed
    s = chronological_split(df, "Timestamp", val_fraction=0.1, test_fraction=0.2)
    parsed = pd.to_datetime(df["Timestamp"])
    assert parsed.iloc[s.train].max() < parsed.iloc[s.validation].min()
    assert parsed.iloc[s.validation].max() < parsed.iloc[s.test].min()
    assert s.manifest["sizes"] == {"train": 70, "validation": 10, "test": 20}


def test_chronological_split_rejects_bad_timestamps():
    with pytest.raises(ValueError, match="unparseable"):
        chronological_split(pd.DataFrame({"t": ["2026-01-01", "nope"]}), "t", val_fraction=0, test_fraction=0.5)


def test_stratified_split_reproducible_and_disjoint():
    y = pd.Series(["a"] * 80 + ["b"] * 20)
    s1 = stratified_random_split(y, val_fraction=0.1, test_fraction=0.2, seed=3)
    s2 = stratified_random_split(y, val_fraction=0.1, test_fraction=0.2, seed=3)
    assert s1.manifest["index_hashes"] == s2.manifest["index_hashes"]
    all_idx = np.concatenate([s1.train, s1.validation, s1.test])
    assert len(set(all_idx)) == 100
    assert (y.iloc[s1.test] == "b").sum() == 4


def test_column_split():
    df = pd.DataFrame({"split": ["train", "val", "test", "TEST"]})
    s = column_split(df, "split")
    assert s.test.tolist() == [2, 3] and s.validation.tolist() == [1]
    with pytest.raises(ValueError):
        column_split(pd.DataFrame({"split": ["holdout"]}), "split")


def test_benchmark_shape():
    df = pd.DataFrame({"x": range(50)})
    res = benchmark_inference(lambda d: d.sum(), df, batch_size=10, repeats=3)
    assert res["batch_rows"] == 10 and res["error_count"] == 0
    assert res["throughput_rows_per_s"] > 0
