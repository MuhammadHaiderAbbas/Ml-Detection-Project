"""Clearly labelled synthetic flow data for exercising the software.

The generated rows loosely imitate the *shape* of CICFlowMeter flow records so
the pipeline can be demonstrated and tested without private or unavailable
data. They carry no information about real attacks. Every class label is
prefixed ``SYNTH_`` (except ``Benign``), the output file name contains
``SYNTHETIC``, and a provenance sidecar file is written next to it.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..provenance import Provenance, sha256_file

FEATURES = [
    "Dst Port", "Protocol", "Flow Duration", "Tot Fwd Pkts", "Tot Bwd Pkts",
    "TotLen Fwd Pkts", "TotLen Bwd Pkts", "Fwd Pkt Len Mean", "Bwd Pkt Len Mean",
    "Flow Byts/s", "Flow Pkts/s", "SYN Flag Cnt",
]
CLASSES = ("Benign", "SYNTH_DoS", "SYNTH_PortScan")


def _class_rows(rng: np.random.Generator, cls: str, n: int, shift: float) -> dict[str, np.ndarray]:
    if cls == "Benign":
        port = rng.choice([80, 443, 53, 22, 8080], size=n, p=[0.25, 0.5, 0.15, 0.05, 0.05])
        dur = rng.lognormal(11 + shift, 1.5, n)
        fwd = rng.poisson(12 * (1 + shift), n) + 1
        bwd = rng.poisson(10 * (1 + shift), n)
        fwd_len = rng.lognormal(6, 0.8, n)
        bwd_len = rng.lognormal(6.5, 0.9, n)
        syn = rng.binomial(1, 0.3, n)
    elif cls == "SYNTH_DoS":
        port = np.full(n, 80)
        dur = rng.lognormal(9, 1.0, n)
        fwd = rng.poisson(60, n) + 1
        bwd = rng.poisson(2, n)
        fwd_len = rng.lognormal(4, 0.5, n)
        bwd_len = rng.lognormal(3, 0.5, n)
        syn = rng.binomial(1, 0.9, n)
    else:
        port = rng.integers(1, 65535, n)
        dur = rng.lognormal(5, 1.0, n)
        fwd = rng.poisson(1, n) + 1
        bwd = rng.poisson(1, n)
        fwd_len = rng.lognormal(1, 0.5, n)
        bwd_len = rng.lognormal(1, 0.5, n)
        syn = rng.binomial(1, 0.95, n)
    proto = np.where(port == 53, 17, 6)
    tot_fwd = fwd * fwd_len
    tot_bwd = bwd * bwd_len
    secs = np.maximum(dur, 1) / 1e6
    return {
        "Dst Port": port, "Protocol": proto, "Flow Duration": np.round(dur).astype(np.int64),
        "Tot Fwd Pkts": fwd, "Tot Bwd Pkts": bwd,
        "TotLen Fwd Pkts": np.round(tot_fwd, 1), "TotLen Bwd Pkts": np.round(tot_bwd, 1),
        "Fwd Pkt Len Mean": np.round(fwd_len, 3), "Bwd Pkt Len Mean": np.round(bwd_len, 3),
        "Flow Byts/s": np.round((tot_fwd + tot_bwd) / secs, 3),
        "Flow Pkts/s": np.round((fwd + bwd) / secs, 3), "SYN Flag Cnt": syn,
    }


def generate_synthetic_flows(
    n_rows: int = 5000,
    *,
    seed: int = 7,
    class_weights: tuple[float, float, float] = (0.8, 0.12, 0.08),
    drift_after_fraction: float | None = None,
    drift_strength: float = 0.6,
    inject_invalid_rows: bool = True,
    start: datetime = datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc),
) -> pd.DataFrame:
    """Generate synthetic flows; optionally shift benign traffic after a point in time."""
    rng = np.random.default_rng(seed)
    labels = rng.choice(CLASSES, size=n_rows, p=np.asarray(class_weights) / sum(class_weights))
    offsets = np.sort(rng.uniform(0, 3 * 24 * 3600, n_rows))
    drift_from = int(n_rows * drift_after_fraction) if drift_after_fraction is not None else n_rows
    frame = pd.DataFrame(index=range(n_rows), columns=FEATURES, dtype=object)
    for cls in CLASSES:
        for drifted in (False, True):
            mask = (labels == cls) & ((np.arange(n_rows) >= drift_from) == drifted)
            n = int(mask.sum())
            if not n:
                continue
            rows = _class_rows(rng, cls, n, drift_strength if (drifted and cls == "Benign") else 0.0)
            for col in FEATURES:
                frame.loc[mask, col] = rows[col]
    frame.insert(0, "Flow ID", [f"synth-{i:07d}" for i in range(n_rows)])
    frame.insert(1, "Src IP", [f"10.0.{rng.integers(0, 4)}.{rng.integers(2, 250)}" for _ in range(n_rows)])
    # Destinations come from a small documentation-range pool (RFC 5737), so "top destinations" is meaningful.
    frame.insert(2, "Dst IP", [f"192.0.2.{rng.integers(10, 30)}" for _ in range(n_rows)])
    frame.insert(3, "Timestamp", [(start + timedelta(seconds=float(o))).strftime("%Y-%m-%d %H:%M:%S") for o in offsets])
    frame["Label"] = labels
    frame = frame.astype(str)

    if inject_invalid_rows and n_rows >= 50:
        # Deliberately malformed rows so validation and rejection reporting are exercised.
        bad = rng.choice(n_rows, size=6, replace=False)
        frame.loc[bad[0], "Flow Byts/s"] = "Infinity"
        frame.loc[bad[1], "Flow Pkts/s"] = "NaN"
        frame.loc[bad[2], "Tot Fwd Pkts"] = "abc"
        frame.loc[bad[3], "Flow Duration"] = "-5"
        frame.loc[bad[4], "Label"] = ""
        frame.loc[bad[5]] = frame.columns.tolist()  # repeated header line, as in CIC exports
    return frame


def write_synthetic_dataset(path: str | Path, **kwargs: Any) -> dict[str, Any]:
    path = Path(path)
    if "SYNTHETIC" not in path.name.upper():
        raise ValueError("synthetic dataset file names must contain 'SYNTHETIC'")
    path.parent.mkdir(parents=True, exist_ok=True)
    df = generate_synthetic_flows(**kwargs)
    df.to_csv(path, index=False)
    sidecar = {
        "provenance": Provenance.SYNTHETIC_DEMO.value,
        "warning": "Synthetic data for software demonstration and testing only. Not real network traffic.",
        "generator": "adaptive_ids.research.synthetic.generate_synthetic_flows",
        "parameters": {k: str(v) for k, v in kwargs.items()},
        "rows": len(df),
        "sha256": sha256_file(path),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    Path(str(path) + ".provenance.json").write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
    return sidecar
