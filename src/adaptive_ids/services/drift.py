"""Drift monitoring service: configure analyses, run them, manage drift events.

A drift event is a signal for an analyst to look at. Nothing here changes a
model's lifecycle status: retraining or promotion always goes through the
model registry's explicit, audited approval steps.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, sessionmaker

from ..db.models import (
    DatasetImport,
    DriftAnalysis,
    DriftEvent,
    DriftEventNote,
    DriftWindow,
    Event,
    ModelVersion,
    Prediction,
    User,
    utcnow,
)
from ..db.session import session_scope
from ..drift import DriftConfig, DriftConfigError, DriftFrames, analyze
from ..settings import Settings
from . import audit
from .errors import Conflict, InvalidRequest, NotFound
from .imports import get_schema

log = logging.getLogger(__name__)

EVENT_STATUSES = ("new", "acknowledged", "investigating", "closed")
TRANSITIONS = {
    "new": {"acknowledged", "investigating", "closed"},
    "acknowledged": {"investigating", "closed"},
    "investigating": {"closed"},
    "closed": {"investigating"},
}
MAX_EVENTS_PER_ANALYSIS = 1_000_000


def _parse_dt(v: Any) -> datetime | None:
    if v in (None, ""):
        return None
    try:
        ts = pd.Timestamp(v)
    except (ValueError, TypeError) as exc:
        raise InvalidRequest(f"invalid timestamp {v!r}") from exc
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    return ts.to_pydatetime()


def _check_spec(db: Session, spec: dict[str, Any], label: str) -> dict[str, Any]:
    if not isinstance(spec, dict) or "import_id" not in spec:
        raise InvalidRequest(f"{label} needs an import_id")
    imp = db.get(DatasetImport, int(spec["import_id"]))
    if imp is None:
        raise NotFound(f"{label} import not found")
    if imp.status != "completed":
        raise Conflict(f"{label} import is {imp.status}; only completed imports can be analysed")
    since, until = _parse_dt(spec.get("since")), _parse_dt(spec.get("until"))
    if since and until and since >= until:
        raise InvalidRequest(f"{label}: 'since' must be before 'until'")
    return {"import_id": imp.id, "since": since.isoformat() if since else None, "until": until.isoformat() if until else None,
            "schema_id": imp.schema_id, "dataset": f"{imp.dataset_name}@{imp.dataset_version}", "provenance": imp.provenance}


def start_analysis(db: Session, payload: dict[str, Any], settings: Settings, actor: User, client_ip: str | None = None) -> DriftAnalysis:
    name = str(payload.get("name") or "").strip()
    if not 1 <= len(name) <= 200:
        raise InvalidRequest("name must be 1-200 characters")
    ref = _check_spec(db, payload.get("reference") or {}, "reference")
    cur = _check_spec(db, payload.get("current") or {}, "current")
    if ref["schema_id"] != cur["schema_id"]:
        raise InvalidRequest("reference and current imports must use the same feature schema")
    try:
        cfg = DriftConfig.from_dict(payload.get("config"))
    except DriftConfigError as exc:
        raise InvalidRequest(str(exc)) from exc
    window = dict(payload.get("window") or {"mode": "events", "size": 500})
    if window.get("mode") == "events":
        size = int(window.get("size", 500))
        if not 50 <= size <= 1_000_000:
            raise InvalidRequest("window size must be between 50 and 1,000,000 events")
        window = {"mode": "events", "size": size}
    elif window.get("mode") == "time":
        if window.get("bucket") not in ("hour", "day", "week"):
            raise InvalidRequest("time windows need bucket hour, day or week")
        window = {"mode": "time", "bucket": window["bucket"]}
    else:
        raise InvalidRequest("window mode must be 'events' or 'time'")

    mv = None
    if payload.get("model_version_id"):
        mv = db.get(ModelVersion, int(payload["model_version_id"]))
        if mv is None:
            raise NotFound("model version not found")
    elif payload.get("use_active_model", True):
        mv = db.scalar(select(ModelVersion).where(ModelVersion.status == "active"))
    schema_feats = get_schema(settings, ref["schema_id"]).feature_names
    model_feats = [f["name"] for f in mv.feature_schema["features"]] if mv is not None else None
    feats = payload.get("features") or model_feats or schema_feats
    unknown = sorted(set(feats) - set(schema_feats))
    if unknown:
        raise InvalidRequest(f"features not in schema {ref['schema_id']}: {unknown}")

    a = DriftAnalysis(name=name, model_version_id=mv.id if mv else None, reference_spec=ref, current_spec=cur,
                      window_spec=window, features=list(feats), config=cfg.to_dict(), status="queued",
                      created_by_id=actor.id)
    db.add(a)
    db.flush()
    audit.record(db, "drift.analysis_start", actor=actor, entity_type="drift_analysis", entity_id=a.id,
                 details={"name": name, "reference": ref["import_id"], "current": cur["import_id"],
                          "model_version_id": a.model_version_id}, client_ip=client_ip)
    return a


def _frame(db: Session, spec: dict[str, Any], features: list[str], model_version_id: int | None) -> pd.DataFrame:
    q = select(Event.id, Event.occurred_at, Event.features, Event.dataset_label).where(Event.import_id == spec["import_id"])
    if spec.get("since"):
        q = q.where(Event.occurred_at >= _parse_dt(spec["since"]))
    if spec.get("until"):
        q = q.where(Event.occurred_at < _parse_dt(spec["until"]))
    count = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    if count > MAX_EVENTS_PER_ANALYSIS:
        raise InvalidRequest(f"window has {count} events; the limit per analysis is {MAX_EVENTS_PER_ANALYSIS}")
    rows = db.execute(q).all()
    df = pd.DataFrame({
        "event_id": [r.id for r in rows],
        "occurred_at": pd.to_datetime([r.occurred_at for r in rows], utc=True),
        "label": [r.dataset_label for r in rows],
    })
    for f in features:
        df[f] = np.array([np.nan if r.features.get(f) is None else r.features.get(f) for r in rows], dtype="float64")
    if model_version_id is not None and len(df):
        preds = db.execute(select(Prediction.event_id, Prediction.predicted_class, Prediction.status, Prediction.is_suspicious)
                           .join(Event, Event.id == Prediction.event_id)
                           .where(and_(Event.import_id == spec["import_id"], Prediction.model_version_id == model_version_id))).all()
        p = pd.DataFrame(preds, columns=["event_id", "predicted_class", "status", "is_suspicious"])
        df = df.merge(p, on="event_id", how="left")
    return df


def run_analysis(factory: sessionmaker[Session], analysis_id: int) -> None:
    with session_scope(factory) as db:
        a = db.get(DriftAnalysis, analysis_id)
        if a is None or a.status != "queued":
            return
        a.status, a.started_at = "running", utcnow()
    try:
        with session_scope(factory) as db:
            a = db.get(DriftAnalysis, analysis_id)
            mv = db.get(ModelVersion, a.model_version_id) if a.model_version_id else None
            ref = _frame(db, a.reference_spec, a.features, a.model_version_id)
            cur = _frame(db, a.current_spec, a.features, a.model_version_id)
            if mv is not None and ("predicted_class" not in cur.columns or cur["predicted_class"].isna().all()):
                ref = ref.drop(columns=["predicted_class", "status", "is_suspicious"], errors="ignore")
                cur = cur.drop(columns=["predicted_class", "status", "is_suspicious"], errors="ignore")
            if ref.empty or cur.empty:
                raise InvalidRequest("reference or current window contains no events")
            res = analyze(DriftFrames(ref, cur, a.features, mv.benign_label if mv else None), a.window_spec,
                          DriftConfig.from_dict(a.config))
            for w in res.windows:
                db.add(DriftWindow(analysis_id=a.id, window_index=w["index"], start=_parse_dt(w["start"]), end=_parse_dt(w["end"]),
                                   n_events=w["n_events"], max_feature_psi=w["max_feature_psi"],
                                   drifted_features=w["drifted_features"], features=w["features"],
                                   prediction=w["prediction"], performance=w["performance"]))
            for e in res.events:
                db.add(DriftEvent(analysis_id=a.id, drift_type=e["drift_type"], signal=e["signal"], severity=e["severity"],
                                  rule=e["rule"], window_index=e["window_index"], detected_at=_parse_dt(e["detected_at"]),
                                  details=_jsonable(e["details"]), status="new"))
            if mv is not None and "predicted_class" not in cur.columns:
                res.summary["prediction"] = {"status": "not_assessable", "reason": f"model {mv.version_id} has not scored these imports"}
            a.summary, a.overall, a.timings = _jsonable(res.summary), _jsonable(res.overall), res.timings
            a.n_reference, a.n_current = len(ref), len(cur)
            a.status, a.completed_at = "completed", utcnow()
    except (InvalidRequest, ValueError) as exc:
        _fail(factory, analysis_id, str(getattr(exc, "message", exc)))
    except Exception:
        log.exception("drift analysis %s failed", analysis_id)
        _fail(factory, analysis_id, "internal error during drift analysis (see server log)")


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (np.floating, float)):
        return None if not np.isfinite(obj) else float(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    return obj


def _fail(factory: sessionmaker[Session], analysis_id: int, message: str) -> None:
    with session_scope(factory) as db:
        a = db.get(DriftAnalysis, analysis_id)
        if a:
            a.status, a.error, a.completed_at = "failed", message, utcnow()


def get_analysis(db: Session, analysis_id: int) -> DriftAnalysis:
    a = db.get(DriftAnalysis, analysis_id)
    if a is None:
        raise NotFound("drift analysis not found")
    return a


def windows(db: Session, analysis_id: int) -> list[DriftWindow]:
    get_analysis(db, analysis_id)
    return list(db.scalars(select(DriftWindow).where(DriftWindow.analysis_id == analysis_id).order_by(DriftWindow.window_index)))


def list_events(db: Session, *, status: list[str] | None, drift_type: str | None, analysis_id: int | None,
                limit: int, offset: int) -> tuple[list[DriftEvent], int]:
    q = select(DriftEvent)
    if status:
        q = q.where(DriftEvent.status.in_(status))
    if drift_type:
        q = q.where(DriftEvent.drift_type == drift_type)
    if analysis_id:
        q = q.where(DriftEvent.analysis_id == analysis_id)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    return list(db.scalars(q.order_by(DriftEvent.created_at.desc(), DriftEvent.id.desc()).limit(limit).offset(offset))), total


def get_event(db: Session, event_id: int) -> DriftEvent:
    e = db.get(DriftEvent, event_id)
    if e is None:
        raise NotFound("drift event not found")
    return e


def event_notes(db: Session, event_id: int) -> list[tuple[DriftEventNote, str | None]]:
    users = {u.id: u.username for u in db.scalars(select(User))}
    notes = db.scalars(select(DriftEventNote).where(DriftEventNote.event_id == event_id).order_by(DriftEventNote.created_at, DriftEventNote.id))
    return [(n, users.get(n.author_id)) for n in notes]


def transition_event(db: Session, event_id: int, to_status: str, note: str | None, actor: User, client_ip: str | None = None) -> DriftEvent:
    e = get_event(db, event_id)
    if to_status not in EVENT_STATUSES:
        raise InvalidRequest(f"status must be one of {EVENT_STATUSES}")
    if to_status not in TRANSITIONS[e.status]:
        raise InvalidRequest(f"cannot move a drift event from {e.status} to {to_status}")
    note = (note or "").strip()
    if to_status == "closed" and not note:
        raise InvalidRequest("closing a drift event requires a note recording the outcome of the review")
    db.add(DriftEventNote(event_id=e.id, author_id=actor.id, kind="status",
                          body=f"{e.status} -> {to_status}" + (f": {note}" if note else "")))
    old, e.status, e.updated_at = e.status, to_status, utcnow()
    audit.record(db, "drift.event_status", actor=actor, entity_type="drift_event", entity_id=e.id,
                 details={"from": old, "to": to_status}, client_ip=client_ip)
    return e


def add_event_note(db: Session, event_id: int, body: str, actor: User) -> DriftEventNote:
    e = get_event(db, event_id)
    body = (body or "").strip()
    if not 1 <= len(body) <= 10_000:
        raise InvalidRequest("note must be 1-10000 characters")
    n = DriftEventNote(event_id=e.id, author_id=actor.id, kind="note", body=body)
    db.add(n)
    e.updated_at = utcnow()
    db.flush()
    return n


def monitoring_status(db: Session) -> dict[str, Any]:
    latest = db.scalar(select(DriftAnalysis).where(DriftAnalysis.status == "completed").order_by(DriftAnalysis.completed_at.desc()))
    open_events = dict(db.execute(select(DriftEvent.drift_type, func.count()).where(DriftEvent.status != "closed")
                                  .group_by(DriftEvent.drift_type)).all())
    if latest is None:
        return {"status": "not_configured", "note": "No drift analysis has been run yet.", "open_events": open_events}
    return {"status": "drift_detected" if open_events else "no_open_events", "open_events": open_events,
            "latest_analysis": {"id": latest.id, "name": latest.name, "completed_at": latest.completed_at,
                                "summary": {k: (latest.summary or {}).get(k) for k in ("feature", "prediction", "performance", "concept")}},
            "note": "Drift is a signal for review, not evidence of an attack or model failure."}


def report_markdown(db: Session, analysis_id: int) -> str:
    a = get_analysis(db, analysis_id)
    if a.status != "completed":
        raise Conflict(f"analysis is {a.status}")
    mv = db.get(ModelVersion, a.model_version_id) if a.model_version_id else None
    s, o = a.summary or {}, a.overall or {}
    ev, _ = list_events(db, status=None, drift_type=None, analysis_id=a.id, limit=1000, offset=0)
    demo = "synthetic_demo" in (a.reference_spec.get("provenance"), a.current_spec.get("provenance"))
    lines = [f"# Drift report — {a.name}", ""]
    if demo:
        lines += ["> **SYNTHETIC DEMONSTRATION DATA** — results describe generated data, not real traffic.", ""]
    lines += [
        f"- Analysis #{a.id}, completed {a.completed_at.isoformat() if a.completed_at else 'n/a'}",
        f"- Reference: import #{a.reference_spec['import_id']} ({a.reference_spec['dataset']}) {a.reference_spec.get('since') or ''} – {a.reference_spec.get('until') or ''} · {a.n_reference} events",
        f"- Current: import #{a.current_spec['import_id']} ({a.current_spec['dataset']}) {a.current_spec.get('since') or ''} – {a.current_spec.get('until') or ''} · {a.n_current} events",
        f"- Model: {mv.version_id if mv else 'none (prediction drift and performance not assessed)'}",
        f"- Windows: {a.window_spec}; features tested: {len(a.features)}",
        f"- Thresholds (v{a.config.get('version')}): PSI moderate {a.config['psi_moderate']}, major {a.config['psi_major']}, "
        f"alpha {a.config['alpha']} (Bonferroni), min events {a.config['min_window_events']}, "
        f"error-rate rise moderate {a.config['perf_moderate']}, major {a.config['perf_major']}, ADWIN delta {a.config['adwin_delta']}",
        "", "## Verdicts", "", "| Drift type | Status | Severity |", "|---|---|---|",
    ]
    for k in ("feature", "prediction", "performance", "concept"):
        v = s.get(k) or {}
        lines.append(f"| {k} | {v.get('status', 'n/a')} | {v.get('severity', '—')} |")
    lines += ["", "## Feature comparison (current vs reference)", "",
              "| Feature | PSI | KS D | KS p (Bonferroni) | Ref median | Cur median | Severity |", "|---|---|---|---|---|---|---|"]
    feats = o.get("features", {})
    for f, v in sorted(feats.items(), key=lambda kv: -(kv[1].get("psi") or 0)):
        fmt = lambda x, d=3: "n/a" if x is None else f"{x:.{d}g}" if isinstance(x, float) else str(x)
        lines.append(f"| {f} | {fmt(v.get('psi'))} | {fmt(v.get('ks_d'))} | {fmt(v.get('ks_p_adj'), 2)} | {fmt(v.get('ref_median'), 4)} | {fmt(v.get('cur_median'), 4)} | {v.get('severity')} |")
    perf = o.get("performance") or {}
    lines += ["", "## Performance (labels supplied with the imported files)", "",
              f"- Reference error rate: {perf.get('reference', {}).get('error_rate')}; current: {perf.get('current', {}).get('error_rate')}; "
              f"change: {perf.get('error_rate_change')} → {perf.get('severity')}", "",
              "## Drift events", ""]
    lines += [f"- #{e.id} [{e.drift_type}/{e.severity}] {e.signal}: {e.rule} — status {e.status}" for e in ev] or ["- None"]
    lines += ["", "## Interpretation and limitations", "",
              f"- {s.get('interpretation', '')}",
              "- PSI uses reference-quantile bins; discrete features may have fewer bins than configured.",
              "- Concept drift is reported only as *suspected*, when performance degrades without feature drift, and needs labels.",
              "- Event timestamps without a timezone were interpreted as UTC at import.", ""]
    return "\n".join(lines)


def windows_csv(db: Session, analysis_id: int) -> str:
    a = get_analysis(db, analysis_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["window_index", "start", "end", "n_events", "signal_type", "signal", "psi", "ks_d", "p_adj", "severity", "error_rate"])
    for win in windows(db, a.id):
        for f, v in win.features.items():
            w.writerow([win.window_index, win.start, win.end, win.n_events, "feature", f, v.get("psi"), v.get("ks_d"), v.get("ks_p_adj"), v.get("severity"), ""])
        if win.prediction:
            w.writerow([win.window_index, win.start, win.end, win.n_events, "prediction", "predicted_class_distribution",
                        win.prediction.get("psi"), "", win.prediction.get("chi2_p"), win.prediction.get("severity"), ""])
        if win.performance and win.performance.get("error_rate") is not None:
            w.writerow([win.window_index, win.start, win.end, win.n_events, "performance", "error_rate", "", "", "",
                        win.performance.get("severity"), win.performance.get("error_rate")])
    return buf.getvalue()
