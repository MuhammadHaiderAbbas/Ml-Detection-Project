"""Train/validation/test splitting with recorded, verifiable manifests.

Each split returns positional indices plus a manifest (method, seed, sizes and
a hash of the indices) so an experiment can prove which rows were used for
fitting, model selection and final testing — and that they do not overlap.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ..provenance import sha256_json


@dataclass
class Split:
    train: np.ndarray
    validation: np.ndarray
    test: np.ndarray
    manifest: dict[str, Any] = field(default_factory=dict)


def _finalise(train, val, test, method: str, params: dict[str, Any]) -> Split:
    train, val, test = (np.sort(np.asarray(a, dtype=np.int64)) for a in (train, val, test))
    sets = [set(train.tolist()), set(val.tolist()), set(test.tolist())]
    if sets[0] & sets[1] or sets[0] & sets[2] or sets[1] & sets[2]:
        raise AssertionError("split partitions overlap")
    manifest = {
        "method": method,
        "params": params,
        "sizes": {"train": len(train), "validation": len(val), "test": len(test)},
        "index_hashes": {
            "train": sha256_json(train.tolist()),
            "validation": sha256_json(val.tolist()),
            "test": sha256_json(test.tolist()),
        },
    }
    return Split(train, val, test, manifest)


def _check_fractions(val_fraction: float, test_fraction: float) -> None:
    if not (0 <= val_fraction < 1 and 0 < test_fraction < 1 and val_fraction + test_fraction < 1):
        raise ValueError("fractions must satisfy 0<=val, 0<test, val+test<1")


def chronological_split(
    df: pd.DataFrame, timestamp_column: str, *, val_fraction: float, test_fraction: float, timestamp_format: str | None = None
) -> Split:
    """Oldest rows train, then validation, newest rows test. Ties keep file order."""
    _check_fractions(val_fraction, test_fraction)
    ts = pd.to_datetime(df[timestamp_column], format=timestamp_format, errors="coerce")
    if ts.isna().any():
        raise ValueError(f"{int(ts.isna().sum())} rows have unparseable timestamps in {timestamp_column!r}")
    order = np.argsort(ts.to_numpy(), kind="stable")
    n = len(order)
    n_test = int(round(n * test_fraction))
    n_val = int(round(n * val_fraction))
    n_train = n - n_val - n_test
    split = _finalise(
        order[:n_train], order[n_train : n_train + n_val], order[n_train + n_val :],
        "chronological",
        {"timestamp_column": timestamp_column, "val_fraction": val_fraction, "test_fraction": test_fraction},
    )
    split.manifest["time_ranges"] = {
        name: [str(ts.iloc[idx].min()), str(ts.iloc[idx].max())] if len(idx) else None
        for name, idx in (("train", split.train), ("validation", split.validation), ("test", split.test))
    }
    return split


def stratified_random_split(
    labels: pd.Series, *, val_fraction: float, test_fraction: float, seed: int
) -> Split:
    from sklearn.model_selection import train_test_split

    _check_fractions(val_fraction, test_fraction)
    idx = np.arange(len(labels))
    y = labels.to_numpy()
    rest, test = train_test_split(idx, test_size=test_fraction, stratify=y, random_state=seed)
    if val_fraction:
        rel = val_fraction / (1 - test_fraction)
        train, val = train_test_split(rest, test_size=rel, stratify=y[rest], random_state=seed)
    else:
        train, val = rest, np.array([], dtype=np.int64)
    return _finalise(
        train, val, test, "stratified_random",
        {"val_fraction": val_fraction, "test_fraction": test_fraction, "seed": seed},
    )


def column_split(df: pd.DataFrame, column: str) -> Split:
    """Use a pre-assigned split column with values 'train', 'validation'/'val', 'test'.

    This is the preferred way to reproduce the original dissertation split
    exactly when the original row assignment can be recovered.
    """
    values = df[column].astype(str).str.strip().str.lower().replace({"val": "validation"})
    unknown = sorted(set(values) - {"train", "validation", "test"})
    if unknown:
        raise ValueError(f"unknown split values in {column!r}: {unknown}")
    pos = np.arange(len(df))
    return _finalise(
        pos[(values == "train").to_numpy()],
        pos[(values == "validation").to_numpy()],
        pos[(values == "test").to_numpy()],
        "column", {"column": column},
    )


def manifest_dict(split: Split) -> dict[str, Any]:
    return asdict(split)["manifest"]
