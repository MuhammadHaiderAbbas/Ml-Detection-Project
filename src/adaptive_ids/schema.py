"""Versioned feature schemas.

A schema states which columns are model inputs, which column is the label,
and which columns must never reach the model (identifiers, timestamps and
other post-event or leakage-prone information). Schemas are plain JSON so
they can be reviewed, diffed and hashed.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .provenance import sha256_json

ALLOWED_DTYPES = ("float", "int")
MISSING_POLICIES = ("reject_row", "keep_as_missing")
INFINITE_POLICIES = ("reject_row", "treat_as_missing")


class SchemaError(ValueError):
    """The schema definition itself is invalid."""


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    dtype: str = "float"
    min: float | None = None
    max: float | None = None
    description: str = ""


@dataclass(frozen=True)
class FeatureSchema:
    name: str
    version: str
    features: tuple[FeatureSpec, ...]
    label_column: str | None = None
    benign_label: str | None = None
    timestamp_column: str | None = None
    event_id_column: str | None = None
    excluded_columns: tuple[str, ...] = ()
    context_columns: tuple[str, ...] = ()
    """Non-feature columns kept with each event for investigation (e.g. IPs).
    They never reach the model; they may overlap features or excluded columns."""
    source_column: str | None = None
    """Context column holding the traffic source (e.g. source IP), if any."""
    destination_column: str | None = None
    """Context column holding the traffic destination (e.g. destination IP), if any."""
    missing_value_policy: str = "reject_row"
    infinite_value_policy: str = "reject_row"
    status: str = "unverified"
    notes: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        names = [f.name for f in self.features]
        if not names:
            raise SchemaError("schema must define at least one feature")
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise SchemaError(f"duplicate feature names: {dupes}")
        for f in self.features:
            if f.dtype not in ALLOWED_DTYPES:
                raise SchemaError(f"feature {f.name!r}: dtype must be one of {ALLOWED_DTYPES}")
            if f.min is not None and f.max is not None and f.min > f.max:
                raise SchemaError(f"feature {f.name!r}: min > max")
        # Leakage guards: the label and non-feature metadata may never be inputs.
        forbidden = set(self.excluded_columns)
        for col in (self.label_column, self.timestamp_column, self.event_id_column):
            if col:
                forbidden.add(col)
        leaked = sorted(forbidden.intersection(names))
        if leaked:
            raise SchemaError(
                f"columns {leaked} are label/identifier/excluded columns and cannot be features"
            )
        if self.missing_value_policy not in MISSING_POLICIES:
            raise SchemaError(f"missing_value_policy must be one of {MISSING_POLICIES}")
        if self.infinite_value_policy not in INFINITE_POLICIES:
            raise SchemaError(f"infinite_value_policy must be one of {INFINITE_POLICIES}")

    @property
    def feature_names(self) -> list[str]:
        return [f.name for f in self.features]

    @property
    def all_context_columns(self) -> list[str]:
        cols = list(self.context_columns)
        for c in (self.source_column, self.destination_column):
            if c and c not in cols:
                cols.append(c)
        return cols

    @property
    def schema_hash(self) -> str:
        return sha256_json(self.to_dict())

    @property
    def schema_id(self) -> str:
        return f"{self.name}@{self.version}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["features"] = [asdict(f) for f in self.features]
        d["excluded_columns"] = list(self.excluded_columns)
        d["context_columns"] = list(self.context_columns)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FeatureSchema":
        data = dict(data)
        try:
            features = tuple(FeatureSpec(**f) for f in data.pop("features"))
        except KeyError as exc:
            raise SchemaError("schema is missing 'features'") from exc
        except TypeError as exc:
            raise SchemaError(f"invalid feature definition: {exc}") from exc
        data["excluded_columns"] = tuple(data.get("excluded_columns", ()))
        data["context_columns"] = tuple(data.get("context_columns", ()))
        try:
            return cls(features=features, **data)
        except TypeError as exc:
            raise SchemaError(f"invalid schema field: {exc}") from exc

    @classmethod
    def load(cls, path: str | Path) -> "FeatureSchema":
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    def save(self, path: str | Path) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)
            fh.write("\n")
