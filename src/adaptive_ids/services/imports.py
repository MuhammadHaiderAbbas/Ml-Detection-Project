"""Dataset imports: safe upload storage, validated CSV import, event persistence."""

from __future__ import annotations

import logging
import math
import re
import threading
import uuid
from pathlib import Path
from typing import Any, BinaryIO

import pandas as pd
from sqlalchemy import insert, select
from sqlalchemy.orm import Session, sessionmaker

from ..db.models import DatasetImport, Event, RejectedRow, User, utcnow
from ..db.session import session_scope
from ..ingestion import ROW_NUMBER_COLUMN, ImportLimits, IngestionError, import_csv
from ..provenance import Provenance, sha256_json
from ..schema import FeatureSchema, SchemaError
from ..settings import Settings
from . import audit
from .errors import Conflict, InvalidRequest, NotFound, PermissionDenied

log = logging.getLogger(__name__)

EVENT_BATCH = 5000
_NAME_RE = re.compile(r"^[\w .@()+-]{1,200}$")


# --------------------------------------------------------------------------- schema registry


def list_schemas(settings: Settings) -> dict[str, FeatureSchema]:
    """Schemas the server offers, keyed by ``name@version``. Clients choose by id, never by path."""
    out: dict[str, FeatureSchema] = {}
    for path in sorted(Path(settings.schemas_dir).glob("*.json")):
        try:
            schema = FeatureSchema.load(path)
        except (SchemaError, ValueError, OSError) as exc:
            log.warning("skipping invalid schema %s: %s", path, exc)
            continue
        out[schema.schema_id] = schema
    return out


def get_schema(settings: Settings, schema_id: str) -> FeatureSchema:
    schemas = list_schemas(settings)
    if schema_id not in schemas:
        raise InvalidRequest(f"unknown schema {schema_id!r}; available: {sorted(schemas)}")
    return schemas[schema_id]


# --------------------------------------------------------------------------- upload


def store_upload(stream: BinaryIO, original_filename: str, settings: Settings) -> tuple[Path, int]:
    """Copy an uploaded file to server storage under a generated name, enforcing limits.

    The client's file name is never used as a path. Files must look like text CSV.
    """
    if not original_filename.lower().endswith(".csv"):
        raise InvalidRequest("only .csv files are accepted")
    max_bytes = settings.max_upload_mb * 1024 * 1024
    dest_dir = Path(settings.storage_dir) / "uploads"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{uuid.uuid4()}.csv"
    written = 0
    first = True
    try:
        with open(dest, "wb") as out:
            while chunk := stream.read(1024 * 1024):
                if first:
                    if b"\x00" in chunk[:65536]:
                        raise InvalidRequest("file does not look like a text CSV (binary content)")
                    first = False
                written += len(chunk)
                if written > max_bytes:
                    raise InvalidRequest(f"file exceeds the {settings.max_upload_mb} MB upload limit")
                out.write(chunk)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    if written == 0:
        dest.unlink(missing_ok=True)
        raise InvalidRequest("file is empty")
    return dest, written


def create_import(
    db: Session,
    *,
    stored_path: Path,
    original_filename: str,
    schema: FeatureSchema,
    dataset_name: str,
    dataset_version: str,
    provenance: str,
    data_source: str | None,
    column_mapping: dict[str, str] | None,
    duplicate_policy: str,
    actor: User,
    client_ip: str | None = None,
) -> DatasetImport:
    for label, value in (("dataset_name", dataset_name), ("dataset_version", dataset_version)):
        if not _NAME_RE.match(value or ""):
            raise InvalidRequest(f"{label} must be 1-200 plain characters")
    try:
        prov = Provenance(provenance)
    except ValueError as exc:
        raise InvalidRequest(f"provenance must be one of {[p.value for p in Provenance]}") from exc
    if prov is Provenance.ORIGINAL_DISSERTATION:
        raise InvalidRequest("imports cannot be labelled 'original_dissertation'")
    if duplicate_policy not in ("keep", "drop"):
        raise InvalidRequest("duplicate_policy must be 'keep' or 'drop'")
    mapping = {str(k): str(v) for k, v in (column_mapping or {}).items()}
    record = DatasetImport(
        import_uid=str(uuid.uuid4()),
        dataset_name=dataset_name,
        dataset_version=dataset_version,
        provenance=prov.value,
        data_source=data_source,
        original_filename=Path(original_filename).name[:255],
        stored_path=str(stored_path),
        schema_id=schema.schema_id,
        schema_hash=schema.schema_hash,
        column_mapping=mapping,
        column_mapping_hash=sha256_json(mapping),
        duplicate_policy=duplicate_policy,
        status="queued",
        created_by_id=actor.id,
    )
    db.add(record)
    db.flush()
    audit.record(db, "import.create", actor=actor, entity_type="import", entity_id=record.id,
                 details={"dataset": f"{dataset_name}@{dataset_version}", "provenance": prov.value,
                          "file": record.original_filename}, client_ip=client_ip)
    return record


# --------------------------------------------------------------------------- processing


class CancelRegistry:
    """In-process cancellation flags for running imports."""

    def __init__(self) -> None:
        self._events: dict[int, threading.Event] = {}
        self._lock = threading.Lock()

    def get(self, import_id: int) -> threading.Event:
        with self._lock:
            return self._events.setdefault(import_id, threading.Event())

    def discard(self, import_id: int) -> None:
        with self._lock:
            self._events.pop(import_id, None)


def _clean(v: Any) -> Any:
    if isinstance(v, float) and not math.isfinite(v):
        return None  # JSON (and PostgreSQL) cannot store NaN/inf
    return v


def _event_rows(df: pd.DataFrame, schema: FeatureSchema, import_pk: int) -> tuple[list[dict[str, Any]], int]:
    feats = schema.feature_names
    ts_fmt = schema.metadata.get("timestamp_format") if schema.metadata else None
    occurred = None
    unparsed = 0
    if schema.timestamp_column and schema.timestamp_column in df.columns:
        # Timestamps without a zone are interpreted as UTC (recorded as an import warning).
        occurred = pd.to_datetime(df[schema.timestamp_column], format=ts_fmt, errors="coerce", utc=True)
        unparsed = int(occurred.isna().sum())
    rows = []
    feature_records = df[feats].to_dict(orient="records")
    for i, (idx, feat) in enumerate(zip(df.index, feature_records)):
        context = {}
        for col in schema.all_context_columns:
            if col in df.columns:
                val = df.at[idx, col]
                context[col] = None if pd.isna(val) else (str(val) if not isinstance(val, float) or not val.is_integer() else str(int(val)))
        ts = occurred.iloc[i] if occurred is not None else None
        rows.append({
            "import_id": import_pk,
            "row_number": int(df.at[idx, ROW_NUMBER_COLUMN]),
            "event_key": str(df.at[idx, schema.event_id_column])[:200] if schema.event_id_column in df.columns else None,
            "occurred_at": None if ts is None or pd.isna(ts) else ts.to_pydatetime(),
            "source": context.get(schema.source_column) if schema.source_column else None,
            "destination": context.get(schema.destination_column) if schema.destination_column else None,
            "dataset_label": str(df.at[idx, schema.label_column]) if schema.label_column in df.columns else None,
            "features": {k: _clean(v) for k, v in feat.items()},
            "context": context,
        })
    return rows, unparsed


def run_import(
    factory: sessionmaker[Session], import_id: int, settings: Settings, cancels: CancelRegistry
) -> None:
    """Process a queued import. Runs in a background task with its own sessions."""
    with session_scope(factory) as db:
        rec = db.get(DatasetImport, import_id)
        if rec is None or rec.status != "queued":
            return
        rec.status = "running"
        rec.started_at = utcnow()
        schema_id, path = rec.schema_id, rec.stored_path
        params = dict(dataset_name=rec.dataset_name, dataset_version=rec.dataset_version,
                      provenance=rec.provenance, column_mapping=rec.column_mapping,
                      duplicate_policy=rec.duplicate_policy, import_id=rec.import_uid)
    cancel = cancels.get(import_id)
    try:
        schema = get_schema(settings, schema_id)
        limits = ImportLimits(
            max_file_bytes=settings.max_upload_mb * 1024 * 1024,
            max_rows=settings.max_import_rows,
            max_rejected_rows_kept=settings.max_rejected_rows_stored,
        )
        result = import_csv(path, schema, limits=limits, cancel_event=cancel, **params)
        rows, unparsed = _event_rows(result.data, schema, import_id)
        with session_scope(factory) as db:
            rec = db.get(DatasetImport, import_id)
            if cancel.is_set():
                raise IngestionError("import cancelled by user")
            for start in range(0, len(rows), EVENT_BATCH):
                db.execute(insert(Event), rows[start : start + EVENT_BATCH])
            if len(result.rejected):
                db.execute(insert(RejectedRow), [
                    {"import_id": import_id, "row_number": int(r[ROW_NUMBER_COLUMN]), "reasons": str(r["reasons"])}
                    for r in result.rejected.to_dict(orient="records")
                ])
            r = result.record
            rec.file_sha256, rec.file_bytes = r.file_sha256, r.file_bytes
            rec.total_rows, rec.accepted_rows, rec.rejected_rows = r.total_rows, r.accepted_rows, r.rejected_rows
            rec.duplicate_rows, rec.duplicates_dropped = r.duplicate_rows, r.duplicates_dropped
            rec.rejection_reason_counts, rec.label_distribution = r.rejection_reason_counts, r.label_distribution
            warnings = list(r.warnings)
            if r.extra_columns_ignored:
                warnings.append(f"columns ignored (not in schema): {r.extra_columns_ignored}")
            if unparsed:
                warnings.append(f"{unparsed} timestamps could not be parsed and were stored as empty")
            if schema.timestamp_column:
                warnings.append("timestamps without a timezone were interpreted as UTC")
            rec.warnings = warnings
            rec.status = r.status
            rec.completed_at = utcnow()
    except IngestionError as exc:
        _fail(factory, import_id, str(exc), "cancelled" if cancel.is_set() else "failed")
    except Exception:  # unexpected: keep details in server logs, store a safe message
        log.exception("import %s failed", import_id)
        _fail(factory, import_id, "internal error while processing the import (see server log)", "failed")
    finally:
        cancels.discard(import_id)


def _fail(factory: sessionmaker[Session], import_id: int, message: str, status: str) -> None:
    with session_scope(factory) as db:
        rec = db.get(DatasetImport, import_id)
        if rec:
            rec.status = status
            rec.errors = [*rec.errors, message]
            rec.completed_at = utcnow()


def cancel_import(db: Session, import_id: int, cancels: CancelRegistry, actor: User, client_ip: str | None) -> DatasetImport:
    rec = db.get(DatasetImport, import_id)
    if rec is None:
        raise NotFound("import not found")
    if rec.status not in ("queued", "running"):
        raise Conflict(f"import is already {rec.status}")
    if actor.role != "admin" and rec.created_by_id != actor.id:
        raise PermissionDenied("only the user who started an import (or an admin) can cancel it")
    cancels.get(import_id).set()
    if rec.status == "queued":
        rec.status = "cancelled"
        rec.completed_at = utcnow()
        rec.errors = [*rec.errors, "import cancelled by user"]
    audit.record(db, "import.cancel", actor=actor, entity_type="import", entity_id=import_id, client_ip=client_ip)
    return rec


def get_import(db: Session, import_id: int) -> DatasetImport:
    rec = db.get(DatasetImport, import_id)
    if rec is None:
        raise NotFound("import not found")
    return rec


def rejected_rows(db: Session, import_id: int, limit: int, offset: int) -> tuple[list[RejectedRow], int]:
    from sqlalchemy import func

    get_import(db, import_id)
    q = select(RejectedRow).where(RejectedRow.import_id == import_id)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = list(db.scalars(q.order_by(RejectedRow.row_number).limit(limit).offset(offset)))
    return rows, total
