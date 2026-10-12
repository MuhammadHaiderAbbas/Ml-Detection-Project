"""Configurable data retention (spec §17).

Policy (``configs/retention.json``, every limit optional, ``null`` = keep forever):

* ``imports_days`` - imports older than this are deleted with everything derived from
  them: events, rejected rows, scoring runs, predictions, alerts and alert notes.
  An import is **kept as evidence** while a model evaluation used it or any of its alerts
  is linked to an incident; those are reported, never deleted automatically.
* ``upload_files_days`` - the stored copy of an uploaded CSV is deleted after this many
  days (data minimisation). The import record and its events stay; only re-processing
  the original file becomes impossible.
* ``audit_days`` - audit records older than this are deleted. At least 90 days are kept.
* ``sessions_days`` - expired or revoked session rows older than this are deleted.

``plan`` only reports. ``apply`` deletes and writes one ``retention.purge`` audit record
with the counts, so the purge itself is always accounted for.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from ..db.models import Alert, AuditLog, DatasetImport, Event, ModelEvaluation, SessionToken, User, utcnow
from . import audit

MIN_AUDIT_DAYS = 90


class RetentionError(ValueError):
    pass


@dataclass(frozen=True)
class RetentionPolicy:
    version: str = "1.0.0"
    imports_days: int | None = None
    upload_files_days: int | None = None
    audit_days: int | None = None
    sessions_days: int | None = 30

    def __post_init__(self) -> None:
        for f in ("imports_days", "upload_files_days", "audit_days", "sessions_days"):
            v = getattr(self, f)
            if v is not None and (not isinstance(v, int) or v < 1):
                raise RetentionError(f"{f} must be a positive whole number of days or null")
        if self.audit_days is not None and self.audit_days < MIN_AUDIT_DAYS:
            raise RetentionError(f"audit_days must be at least {MIN_AUDIT_DAYS}")

    @classmethod
    def load(cls, path: str | Path) -> "RetentionPolicy":
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RetentionError(f"cannot read retention policy {path}: {exc}") from exc
        data = {k: v for k, v in data.items() if not k.startswith("_")}
        unknown = set(data) - {f.name for f in fields(cls)}
        if unknown:
            raise RetentionError(f"unknown retention settings: {sorted(unknown)}")
        return cls(**data)


def _evidence_import_ids(db: Session) -> dict[int, str]:
    reasons: dict[int, str] = {}
    for (iid,) in db.execute(select(ModelEvaluation.import_id).distinct()):
        reasons[iid] = "used by a model evaluation"
    for (iid,) in db.execute(select(Alert.import_id).where(Alert.incident_id.is_not(None)).distinct()):
        reasons.setdefault(iid, "has alerts linked to an incident")
    return reasons


def plan(db: Session, policy: RetentionPolicy, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or utcnow()
    out: dict[str, Any] = {"policy": asdict(policy), "as_of": now.isoformat(), "imports": [], "kept_as_evidence": [],
                           "upload_files": [], "audit_records": 0, "sessions": 0}
    if policy.imports_days is not None:
        cutoff = now - timedelta(days=policy.imports_days)
        evidence = _evidence_import_ids(db)
        for imp in db.scalars(select(DatasetImport).where(DatasetImport.created_at < cutoff,
                                                          DatasetImport.status.not_in(("queued", "running")))):
            row = {"id": imp.id, "dataset": f"{imp.dataset_name}@{imp.dataset_version}", "created_at": imp.created_at.isoformat(),
                   "events": db.scalar(select(func.count(Event.id)).where(Event.import_id == imp.id)) or 0}
            if imp.id in evidence:
                out["kept_as_evidence"].append({**row, "reason": evidence[imp.id]})
            else:
                out["imports"].append(row)
    if policy.upload_files_days is not None:
        cutoff = now - timedelta(days=policy.upload_files_days)
        for imp in db.scalars(select(DatasetImport).where(DatasetImport.created_at < cutoff,
                                                          DatasetImport.status.not_in(("queued", "running")))):
            if imp.stored_path and Path(imp.stored_path).is_file():
                out["upload_files"].append({"import_id": imp.id, "file": Path(imp.stored_path).name})
    if policy.audit_days is not None:
        out["audit_records"] = db.scalar(select(func.count(AuditLog.id)).where(
            AuditLog.at < now - timedelta(days=policy.audit_days))) or 0
    if policy.sessions_days is not None:
        out["sessions"] = db.scalar(select(func.count(SessionToken.id)).where(*_stale_sessions(now, policy.sessions_days))) or 0
    return out


def _stale_sessions(now: datetime, days: int):
    cutoff = now - timedelta(days=days)
    return (or_(SessionToken.expires_at < cutoff, SessionToken.revoked_at < cutoff),)


def apply(db: Session, policy: RetentionPolicy, *, actor: User | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Delete what ``plan`` reports, in one transaction, and audit the counts."""
    now = now or utcnow()
    report = plan(db, policy, now=now)
    ids = [r["id"] for r in report["imports"]]
    files_removed = 0
    if ids:
        paths = [p for (p,) in db.execute(select(DatasetImport.stored_path).where(DatasetImport.id.in_(ids)))]
        db.execute(delete(DatasetImport).where(DatasetImport.id.in_(ids)))  # cascades to events, runs, alerts ...
        for p in paths:
            if p and Path(p).is_file():
                Path(p).unlink()
                files_removed += 1
    for f in report["upload_files"]:
        if f["import_id"] in ids:
            continue
        imp = db.get(DatasetImport, f["import_id"])
        if imp and imp.stored_path and Path(imp.stored_path).is_file():
            Path(imp.stored_path).unlink()
            files_removed += 1
            imp.warnings = [*imp.warnings, f"stored upload removed by retention policy v{policy.version} on {now.date()}"]
    audit_deleted = sessions_deleted = 0
    if policy.audit_days is not None:
        audit_deleted = db.execute(delete(AuditLog).where(AuditLog.at < now - timedelta(days=policy.audit_days))).rowcount or 0
    if policy.sessions_days is not None:
        sessions_deleted = db.execute(delete(SessionToken).where(*_stale_sessions(now, policy.sessions_days))).rowcount or 0
    summary = {"policy_version": policy.version, "imports_deleted": len(ids),
               "events_deleted": sum(r["events"] for r in report["imports"]), "upload_files_deleted": files_removed,
               "kept_as_evidence": [r["id"] for r in report["kept_as_evidence"]], "audit_records_deleted": audit_deleted,
               "sessions_deleted": sessions_deleted}
    audit.record(db, "retention.purge", actor=actor, actor_name=None if actor else "cli", details=summary)
    return {**report, "applied": summary}
