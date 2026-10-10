"""CSV import with validation, rejected-row reporting and import records.

Imported files are treated as untrusted input. Values are read as text and
validated against a :class:`FeatureSchema` before any numeric conversion is
trusted. Rows that cannot be processed safely are rejected with explicit
reasons rather than silently coerced.
"""

from __future__ import annotations

import csv
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from ..provenance import Provenance, sha256_file, sha256_json
from ..schema import FeatureSchema

MISSING_TOKENS = frozenset({"", "nan", "null", "none", "na", "n/a"})
POS_INF_TOKENS = frozenset({"inf", "+inf", "infinity", "+infinity"})
NEG_INF_TOKENS = frozenset({"-inf", "-infinity"})

ROW_NUMBER_COLUMN = "_row_number"
"""1-based data row number in the source file (header line excluded)."""


class IngestionError(Exception):
    def __init__(self, message: str, record: "ImportRecord | None" = None):
        super().__init__(message)
        self.record = record


class DatasetNotFoundError(IngestionError, FileNotFoundError):
    """The configured dataset file does not exist. No substitute is ever used."""


class DatasetIntegrityError(IngestionError):
    """The file hash does not match the expected hash."""


class SchemaMismatchError(IngestionError):
    """Required columns are missing from the file."""


class ImportLimitError(IngestionError):
    """The file exceeds the configured size or row-count limits."""


class ImportCancelledError(IngestionError):
    """The import was cancelled by the caller."""


@dataclass(frozen=True)
class ImportLimits:
    max_file_bytes: int = 8 * 1024**3
    max_rows: int = 50_000_000
    chunk_rows: int = 200_000
    max_rejected_rows_kept: int = 100_000
    """Rejected rows beyond this many are counted but not kept in memory."""


@dataclass
class ImportRecord:
    import_id: str
    dataset_name: str
    dataset_version: str
    source_path: str
    provenance: str
    schema_id: str
    schema_hash: str
    column_mapping_hash: str
    file_sha256: str | None = None
    file_bytes: int | None = None
    started_at: str = ""
    completed_at: str | None = None
    status: str = "running"
    total_rows: int = 0
    accepted_rows: int = 0
    rejected_rows: int = 0
    duplicate_rows: int = 0
    duplicates_dropped: int = 0
    rejection_reason_counts: dict[str, int] = field(default_factory=dict)
    label_distribution: dict[str, int] = field(default_factory=dict)
    extra_columns_ignored: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ImportResult:
    record: ImportRecord
    data: pd.DataFrame
    """Accepted rows: feature columns (float64), plus label/timestamp/event-id
    columns when defined, plus ``_row_number``."""
    rejected: pd.DataFrame
    """Columns ``_row_number`` and ``reasons`` (may be truncated, see limits)."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_header(path: Path, mapping: dict[str, str], strip: bool) -> list[str]:
    # csv.reader keeps duplicate names as-is (pandas would silently rename them to "x.1").
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as fh:
        header = next(csv.reader(fh), [])
    if strip:
        header = [h.strip() for h in header]
    return [mapping.get(h, h) for h in header]


def check_columns(columns: list[str], schema: FeatureSchema, require_label: bool) -> dict[str, list[str]]:
    required = list(schema.feature_names)
    if require_label and schema.label_column:
        required.append(schema.label_column)
    known = set(required) | set(schema.excluded_columns)
    for col in (schema.label_column, schema.timestamp_column, schema.event_id_column):
        if col:
            known.add(col)
    known |= set(schema.all_context_columns)
    dupes = sorted({c for c in columns if columns.count(c) > 1})
    return {
        "missing": [c for c in required if c not in columns],
        "extra": [c for c in columns if c not in known],
        "duplicated": dupes,
    }


def preview_csv(
    path: str | Path,
    schema: FeatureSchema,
    *,
    column_mapping: dict[str, str] | None = None,
    n_rows: int = 20,
    strip_header_whitespace: bool = True,
    require_label: bool = True,
) -> dict[str, Any]:
    """Return the header, the first rows (as text) and a column compatibility check."""
    path = Path(path)
    if not path.is_file():
        raise DatasetNotFoundError(f"dataset file not found: {path}")
    mapping = column_mapping or {}
    columns = _read_header(path, mapping, strip_header_whitespace)
    rows = pd.read_csv(path, nrows=n_rows, dtype=str, keep_default_na=False, header=0, names=columns)
    return {
        "columns": columns,
        "rows": rows.to_dict(orient="records"),
        "compatibility": check_columns(columns, schema, require_label),
    }


def _validate_chunk(
    chunk: pd.DataFrame, schema: FeatureSchema, require_label: bool
) -> tuple[pd.DataFrame, pd.Series]:
    """Return (numeric feature frame, per-row reason strings; '' means valid)."""
    reasons = pd.Series("", index=chunk.index, dtype=object)

    def add_reason(mask: pd.Series, text: str) -> None:
        if mask.any():
            reasons.loc[mask] = reasons.loc[mask] + text + ";"

    numeric = {}
    for spec in schema.features:
        raw = chunk[spec.name].fillna("").astype(str).str.strip()
        lower = raw.str.lower()
        missing = lower.isin(MISSING_TOKENS)
        pos_inf = lower.isin(POS_INF_TOKENS)
        neg_inf = lower.isin(NEG_INF_TOKENS)
        special = missing | pos_inf | neg_inf
        values = pd.to_numeric(raw.where(~special), errors="coerce").astype("float64")
        # to_numeric may itself parse e.g. "1e999" to inf; treat those as infinite too.
        parsed_inf = np.isinf(values)
        pos_inf = pos_inf | (parsed_inf & (values > 0))
        neg_inf = neg_inf | (parsed_inf & (values < 0))
        invalid = values.isna() & ~special
        values = values.where(~parsed_inf)

        add_reason(invalid, f"{spec.name}:invalid_type")
        if spec.dtype == "int":
            non_integral = values.notna() & (values != np.floor(values))
            add_reason(non_integral, f"{spec.name}:not_integer")

        if schema.missing_value_policy == "reject_row":
            add_reason(missing, f"{spec.name}:missing")
        infinite = pos_inf | neg_inf
        if schema.infinite_value_policy == "reject_row":
            add_reason(infinite, f"{spec.name}:infinite")
        # Under treat_as_missing, infinities become NaN for the preprocessor.

        if spec.min is not None:
            add_reason(values.notna() & (values < spec.min), f"{spec.name}:below_min")
        if spec.max is not None:
            add_reason(values.notna() & (values > spec.max), f"{spec.name}:above_max")
        numeric[spec.name] = values

    if require_label and schema.label_column:
        label = chunk[schema.label_column].fillna("").astype(str).str.strip()
        add_reason(label.str.lower().isin(MISSING_TOKENS), f"{schema.label_column}:missing_label")
        # A repeated header line inside the file (common in CIC CSV exports).
        add_reason(label == schema.label_column, "repeated_header_row")

    return pd.DataFrame(numeric, index=chunk.index), reasons.str.rstrip(";")


def import_csv(
    path: str | Path,
    schema: FeatureSchema,
    *,
    dataset_name: str,
    dataset_version: str,
    provenance: Provenance | str,
    column_mapping: dict[str, str] | None = None,
    expected_sha256: str | None = None,
    require_label: bool = True,
    duplicate_policy: str = "keep",
    strip_header_whitespace: bool = True,
    limits: ImportLimits = ImportLimits(),
    progress: Callable[[int], None] | None = None,
    cancel_event: threading.Event | None = None,
    import_id: str | None = None,
) -> ImportResult:
    """Validate and import a CSV file.

    ``duplicate_policy`` is ``"keep"`` (count only) or ``"drop"`` (keep the first
    occurrence of identical feature+label rows). Raises an :class:`IngestionError`
    subclass, carrying the partially filled :class:`ImportRecord`, on failure.
    """
    if duplicate_policy not in ("keep", "drop"):
        raise ValueError("duplicate_policy must be 'keep' or 'drop'")
    path = Path(path)
    mapping = dict(column_mapping or {})
    record = ImportRecord(
        import_id=import_id or str(uuid.uuid4()),
        dataset_name=dataset_name,
        dataset_version=dataset_version,
        source_path=str(path),
        provenance=Provenance(provenance).value,
        schema_id=schema.schema_id,
        schema_hash=schema.schema_hash,
        column_mapping_hash=sha256_json(mapping),
        started_at=_now(),
    )

    def fail(exc_type: type[IngestionError], message: str, status: str = "failed") -> IngestionError:
        record.status = status
        record.errors.append(message)
        record.completed_at = _now()
        return exc_type(message, record)

    if not path.is_file():
        raise fail(DatasetNotFoundError, f"dataset file not found: {path} (no substitute dataset is used)")
    record.file_bytes = path.stat().st_size
    if record.file_bytes > limits.max_file_bytes:
        raise fail(ImportLimitError, f"file is {record.file_bytes} bytes; limit is {limits.max_file_bytes}")
    record.file_sha256 = sha256_file(path)
    if expected_sha256 and record.file_sha256.lower() != expected_sha256.lower():
        raise fail(
            DatasetIntegrityError,
            f"sha256 mismatch: expected {expected_sha256}, got {record.file_sha256}",
        )

    columns = _read_header(path, mapping, strip_header_whitespace)
    compat = check_columns(columns, schema, require_label)
    if compat["missing"] or compat["duplicated"]:
        raise fail(
            SchemaMismatchError,
            f"incompatible columns for schema {schema.schema_id}: "
            f"missing={compat['missing']} duplicated={compat['duplicated']}",
        )
    record.extra_columns_ignored = compat["extra"]

    passthrough = [
        c
        for c in (schema.label_column, schema.timestamp_column, schema.event_id_column)
        if c and c in columns
    ]
    passthrough += [
        c for c in schema.all_context_columns
        if c in columns and c not in passthrough and c not in schema.feature_names
    ]
    accepted_parts: list[pd.DataFrame] = []
    rejected_parts: list[pd.DataFrame] = []
    kept_rejected = 0
    reason_counts: dict[str, int] = {}
    row_offset = 0

    reader = pd.read_csv(
        path, dtype=str, keep_default_na=False, chunksize=limits.chunk_rows, header=0, names=columns
    )
    for chunk in reader:
        if cancel_event is not None and cancel_event.is_set():
            raise fail(ImportCancelledError, "import cancelled by user", status="cancelled")
        chunk.index = pd.RangeIndex(row_offset + 1, row_offset + 1 + len(chunk))
        row_offset += len(chunk)
        if row_offset > limits.max_rows:
            raise fail(ImportLimitError, f"file exceeds the row limit of {limits.max_rows}")

        numeric, reasons = _validate_chunk(chunk, schema, require_label)
        bad = reasons != ""
        for text in reasons[bad]:
            for r in text.split(";"):
                reason_counts[r] = reason_counts.get(r, 0) + 1

        if bad.any() and kept_rejected < limits.max_rejected_rows_kept:
            rej = pd.DataFrame({ROW_NUMBER_COLUMN: reasons[bad].index, "reasons": reasons[bad].values})
            rej = rej.iloc[: limits.max_rejected_rows_kept - kept_rejected]
            kept_rejected += len(rej)
            rejected_parts.append(rej)

        good = numeric.loc[~bad].copy()
        for col in passthrough:
            good[col] = chunk.loc[~bad, col].str.strip()
        good[ROW_NUMBER_COLUMN] = good.index
        accepted_parts.append(good)
        if progress is not None:
            progress(row_offset)

    out_cols = schema.feature_names + passthrough + [ROW_NUMBER_COLUMN]
    data = (
        pd.concat(accepted_parts, ignore_index=True)
        if accepted_parts
        else pd.DataFrame(columns=out_cols)
    )[out_cols]
    rejected = (
        pd.concat(rejected_parts, ignore_index=True)
        if rejected_parts
        else pd.DataFrame(columns=[ROW_NUMBER_COLUMN, "reasons"])
    )

    record.rejected_rows = row_offset - len(data)

    dup_key = schema.feature_names + ([schema.label_column] if schema.label_column in data.columns else [])
    dup_mask = data.duplicated(subset=dup_key, keep="first")
    record.duplicate_rows = int(dup_mask.sum())
    if duplicate_policy == "drop" and record.duplicate_rows:
        data = data.loc[~dup_mask].reset_index(drop=True)
        record.duplicates_dropped = record.duplicate_rows

    record.total_rows = row_offset
    record.accepted_rows = len(data)
    record.rejection_reason_counts = dict(sorted(reason_counts.items(), key=lambda kv: -kv[1]))
    if schema.label_column and schema.label_column in data.columns:
        record.label_distribution = {str(k): int(v) for k, v in data[schema.label_column].value_counts().items()}
    if record.rejected_rows > kept_rejected:
        record.warnings.append(
            f"{record.rejected_rows - kept_rejected} rejected rows were counted but not kept in the rejected-row report"
        )
    if record.total_rows == 0:
        record.warnings.append("file contains no data rows")
    record.status = "completed" if record.accepted_rows else "completed_no_valid_rows"
    record.completed_at = _now()
    return ImportResult(record=record, data=data, rejected=rejected)
