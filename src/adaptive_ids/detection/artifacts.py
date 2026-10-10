"""Trusted model-artifact loading.

pickle/joblib files can execute arbitrary code when loaded. This module only
deserialises an artifact when it is listed in a trusted-artifact manifest and
its SHA-256 matches the recorded hash. The manifest is written by a person who
has verified the artifact's origin (for example, the original MSc project
folder) — it is never generated automatically from whatever file is present.
"""

from __future__ import annotations

import json
import warnings
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..provenance import sha256_file

SUPPORTED_FORMATS = ("joblib", "pickle")


class ArtifactTrustError(Exception):
    """The artifact is not trusted, is missing, or does not match its hash."""


@dataclass(frozen=True)
class ArtifactEntry:
    artifact_id: str
    path: str
    sha256: str
    format: str = "joblib"
    model_name: str = ""
    model_type: str = ""
    provenance: str = "original_dissertation"
    trusted_by: str = ""
    trusted_on: str = ""
    training_python_version: str = ""
    training_sklearn_version: str = ""
    feature_schema_id: str = ""
    training_dataset: str = ""
    notes: str = ""


@dataclass
class LoadedModel:
    model: Any
    entry: ArtifactEntry
    resolved_path: str
    warnings: list[str] = field(default_factory=list)

    @property
    def model_version(self) -> str:
        return f"{self.entry.artifact_id}@{self.entry.sha256[:12]}"

    def describe(self) -> dict[str, Any]:
        return {
            "model_version": self.model_version,
            "resolved_path": self.resolved_path,
            "estimator_class": type(self.model).__name__,
            "load_warnings": list(self.warnings),
            **asdict(self.entry),
        }


class TrustedArtifactManifest:
    def __init__(self, entries: list[ArtifactEntry], base_dir: Path):
        ids = [e.artifact_id for e in entries]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ArtifactTrustError(f"duplicate artifact ids in manifest: {dupes}")
        self.entries = {e.artifact_id: e for e in entries}
        self.base_dir = base_dir

    @classmethod
    def load(cls, path: str | Path) -> "TrustedArtifactManifest":
        path = Path(path)
        if not path.is_file():
            raise ArtifactTrustError(f"trusted-artifact manifest not found: {path}")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        try:
            entries = [ArtifactEntry(**e) for e in data.get("artifacts", [])]
        except TypeError as exc:
            raise ArtifactTrustError(f"invalid manifest entry: {exc}") from exc
        for e in entries:
            if e.format not in SUPPORTED_FORMATS:
                raise ArtifactTrustError(f"{e.artifact_id}: unsupported format {e.format!r}")
            if len(e.sha256) != 64:
                raise ArtifactTrustError(f"{e.artifact_id}: sha256 must be a 64-character hex digest")
        return cls(entries, path.parent)

    def resolve(self, artifact_id: str) -> tuple[ArtifactEntry, Path]:
        if artifact_id not in self.entries:
            raise ArtifactTrustError(
                f"artifact {artifact_id!r} is not listed in the trusted manifest; refusing to load it"
            )
        entry = self.entries[artifact_id]
        p = Path(entry.path)
        return entry, (p if p.is_absolute() else self.base_dir / p)

    def load_model(self, artifact_id: str) -> LoadedModel:
        entry, path = self.resolve(artifact_id)
        model, load_warnings = load_verified_artifact(path, entry.sha256, entry.format, label=artifact_id)
        return LoadedModel(model=model, entry=entry, resolved_path=str(path), warnings=load_warnings)


def load_verified_artifact(
    path: str | Path, expected_sha256: str, fmt: str = "joblib", *, label: str = ""
) -> tuple[Any, list[str]]:
    """Deserialise ``path`` only if its SHA-256 equals ``expected_sha256``.

    Callers must take ``expected_sha256`` from a trusted record (a manifest
    written by a person, or a registry row created from one) — never from the
    file itself.
    """
    path = Path(path)
    label = label or path.name
    if fmt not in SUPPORTED_FORMATS:
        raise ArtifactTrustError(f"{label}: unsupported format {fmt!r}")
    if not path.is_file():
        raise ArtifactTrustError(f"artifact file not found: {path}")
    actual = sha256_file(path)
    if actual.lower() != expected_sha256.lower():
        raise ArtifactTrustError(
            f"artifact {label!r} hash mismatch: manifest {expected_sha256}, file {actual}; refusing to load"
        )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        if fmt == "joblib":
            import joblib

            model = joblib.load(path)
        else:
            import pickle

            with open(path, "rb") as fh:
                model = pickle.load(fh)  # noqa: S301 - hash-verified trusted artifact
    if not hasattr(model, "predict"):
        raise ArtifactTrustError(
            f"artifact {label!r} loaded an object of type {type(model).__name__} with no predict()"
        )
    return model, [f"{w.category.__name__}: {w.message}" for w in caught]


def write_manifest(entries: list[ArtifactEntry], path: str | Path) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"artifacts": [asdict(e) for e in entries]}, fh, indent=2)
        fh.write("\n")
