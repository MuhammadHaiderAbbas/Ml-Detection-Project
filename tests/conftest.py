from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from adaptive_ids.schema import FeatureSchema

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def schema() -> FeatureSchema:
    return FeatureSchema.from_dict(
        {
            "name": "test-schema",
            "version": "1.0.0",
            "status": "verified",
            "label_column": "Label",
            "benign_label": "Benign",
            "timestamp_column": "Timestamp",
            "event_id_column": "Flow ID",
            "excluded_columns": ["Src IP"],
            "features": [
                {"name": "a", "dtype": "float", "min": 0},
                {"name": "b", "dtype": "int"},
                {"name": "c", "dtype": "float", "max": 100},
            ],
        }
    )


@pytest.fixture
def write_csv(tmp_path):
    def _write(rows: list[dict], name: str = "data.csv") -> Path:
        path = tmp_path / name
        pd.DataFrame(rows).to_csv(path, index=False)
        return path

    return _write


def make_rows(n: int, seed: int = 0) -> list[dict]:
    """Small, separable labelled rows for the test schema."""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        attack = i % 4 == 0
        rows.append(
            {
                "Flow ID": f"f{i}",
                "Src IP": "10.0.0.1",
                "Timestamp": f"2026-01-01 00:{i // 60:02d}:{i % 60:02d}",
                "a": float(rng.normal(50 if attack else 5, 1)),
                "b": int(rng.integers(0, 3)),
                "c": float(rng.uniform(0, 10)),
                "Label": "DoS" if attack else "Benign",
            }
        )
    return rows
