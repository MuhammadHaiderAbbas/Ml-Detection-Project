"""Provenance labels and hashing helpers.

Every dataset, experiment and report carries a provenance label so that
original dissertation results, new controlled experiments, live operational
observations and synthetic demonstration data are never confused.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from pathlib import Path
from typing import Any


class Provenance(str, Enum):
    ORIGINAL_DISSERTATION = "original_dissertation"
    """Results or artifacts recovered from the original MSc project."""

    BASELINE_REPRODUCTION = "baseline_reproduction"
    """A re-run of the original model/data under the documented protocol."""

    CONTROLLED_EXPERIMENT = "controlled_experiment"
    """A new experiment run with this codebase on real (public) data."""

    LIVE_OBSERVATION = "live_observation"
    """Predictions on authorised operational traffic (no ground truth implied)."""

    SYNTHETIC_DEMO = "synthetic_demo"
    """Generated data used only to exercise the software. Not research evidence."""


PROVENANCE_BANNERS = {
    Provenance.ORIGINAL_DISSERTATION: "ORIGINAL DISSERTATION RESULT",
    Provenance.BASELINE_REPRODUCTION: "BASELINE REPRODUCTION",
    Provenance.CONTROLLED_EXPERIMENT: "CONTROLLED EXPERIMENT",
    Provenance.LIVE_OBSERVATION: "LIVE OPERATIONAL OBSERVATION — predictions are not confirmed attacks",
    Provenance.SYNTHETIC_DEMO: (
        "SYNTHETIC DEMONSTRATION DATA — generated for software testing only; "
        "these numbers say nothing about real intrusion-detection performance"
    ),
}


def sha256_file(path: str | Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(obj: Any) -> str:
    """Stable hash of a JSON-serialisable object (sorted keys, no whitespace)."""
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
