"""Dashboard summary. Every number comes from database records and carries its counting rule."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import Alert, DatasetImport, Event, Incident, ModelVersion, Prediction, ScoringRun
from .alerts import AlertFilters, list_alerts
from .drift import monitoring_status as drift_status

DEFINITIONS = {
    "events_processed": "Accepted event rows stored from completed imports (rejected rows excluded).",
    "events_scored": "Predictions with status 'ok' (each event counted once per model version).",
    "suspicious_predictions": "Predictions whose class is not the model's benign label. Suspicions, not confirmed attacks.",
    "alerts_by_status": "Alerts created from suspicious predictions, by current analyst-controlled status.",
    "high_priority_alerts": "Open (new or investigating) alerts with severity high or critical under the configured triage rules.",
    "confirmed_attacks": "Incidents an analyst gave the disposition 'confirmed_attack'. The only confirmed-attack count; null until any incident has a disposition.",
    "processing_latency": "Duration of the latest completed scoring run divided by the events it processed.",
    "ingestion_health": "Status of the most recent imports; failed imports are counted in the selected range.",
    "top_sources": "Sources of events with suspicious predictions (open and closed alerts).",
    "drift_monitoring": "Open (not closed) drift events by type, and the verdicts of the latest completed drift analysis.",
}


def summary(
    db: Session,
    *,
    import_id: int | None = None,
    model_version_id: int | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict[str, Any]:
    def window(q, col):
        if since:
            q = q.where(col >= since)
        if until:
            q = q.where(col < until)
        return q

    ev = select(func.count(Event.id)).join(DatasetImport, Event.import_id == DatasetImport.id)
    if import_id:
        ev = ev.where(Event.import_id == import_id)
    events_processed = db.scalar(window(ev, DatasetImport.created_at)) or 0

    pq = select(Prediction.status, Prediction.is_suspicious, func.count()).join(Event, Prediction.event_id == Event.id)
    if import_id:
        pq = pq.where(Event.import_id == import_id)
    if model_version_id:
        pq = pq.where(Prediction.model_version_id == model_version_id)
    pq = window(pq, Prediction.inferred_at).group_by(Prediction.status, Prediction.is_suspicious)
    scored = suspicious = rejected = 0
    for status, sus, n in db.execute(pq):
        if status == "ok":
            scored += n
            suspicious += n if sus else 0
        else:
            rejected += n

    aq = select(Alert.status, Alert.severity, func.count())
    if import_id:
        aq = aq.where(Alert.import_id == import_id)
    if model_version_id:
        aq = aq.where(Alert.model_version_id == model_version_id)
    aq = window(aq, Alert.created_at).group_by(Alert.status, Alert.severity)
    by_status = {s: 0 for s in ("new", "investigating", "resolved", "false_positive")}
    by_severity: dict[str, int] = {}
    high_open = 0
    for status, sev, n in db.execute(aq):
        by_status[status] = by_status.get(status, 0) + n
        by_severity[sev] = by_severity.get(sev, 0) + n
        if status in ("new", "investigating") and sev in ("high", "critical"):
            high_open += n

    inc_q = window(select(Incident.disposition, func.count()), Incident.created_at).group_by(Incident.disposition)
    dispositions = {d: n for d, n in db.execute(inc_q)}
    decided = sum(n for d, n in dispositions.items() if d != "undetermined")

    active = db.scalar(select(ModelVersion).where(ModelVersion.status == "active"))
    last_eval = db.scalar(select(ModelVersion).where(ModelVersion.approved_at.is_not(None))
                          .order_by(ModelVersion.approved_at.desc()))
    last_run = db.scalar(select(ScoringRun).where(ScoringRun.status == "completed").order_by(ScoringRun.completed_at.desc()))
    imports = list(db.scalars(select(DatasetImport).order_by(DatasetImport.created_at.desc()).limit(5)))
    failed_imports = db.scalar(window(select(func.count(DatasetImport.id)).where(DatasetImport.status == "failed"),
                                      DatasetImport.created_at)) or 0
    provenances = sorted({p for (p,) in db.execute(select(DatasetImport.provenance).distinct())})

    def top(col):
        q = (select(col, func.count()).join(Alert, Alert.event_id == Event.id).where(col.is_not(None)))
        if import_id:
            q = q.where(Alert.import_id == import_id)
        if model_version_id:
            q = q.where(Alert.model_version_id == model_version_id)
        q = window(q, Alert.created_at).group_by(col).order_by(func.count().desc()).limit(5)
        return [{"value": v, "alerts": n} for v, n in db.execute(q)]

    recent, _ = list_alerts(db, AlertFilters(import_id=import_id, model_version_id=model_version_id,
                                             since=since, until=until), limit=5, offset=0)
    latency = None
    if last_run and last_run.events_total and last_run.duration_ms is not None:
        latency = {"scoring_run_id": last_run.id, "ms_per_event": last_run.duration_ms / last_run.events_total,
                   "events": last_run.events_total, "duration_ms": last_run.duration_ms}
    return {
        "filters": {"import_id": import_id, "model_version_id": model_version_id, "since": since, "until": until},
        "demo_data_present": "synthetic_demo" in provenances,
        "provenances_present": provenances,
        "events_processed": events_processed,
        "events_scored": scored,
        "events_rejected_at_inference": rejected,
        "suspicious_predictions": suspicious,
        "alerts_by_status": by_status,
        "alerts_by_severity": by_severity,
        "high_priority_open_alerts": high_open,
        "incidents_by_disposition": dispositions,
        "confirmed_attacks": dispositions.get("confirmed_attack", 0) if decided else None,
        "confirmed_attacks_note": None if decided else
            "Unavailable: no incident has an analyst disposition yet. Suspicious predictions are not confirmed attacks.",
        "active_model": None if not active else {"id": active.id, "version_id": active.version_id,
                                                 "provenance": active.provenance, "activated_at": active.activated_at},
        "last_approved_evaluation": None if not last_eval else {
            "model_id": last_eval.id, "version_id": last_eval.version_id, "approved_at": last_eval.approved_at,
            "experiment_id": (last_eval.evaluation or {}).get("experiment_id")},
        "processing_latency": latency,
        "ingestion": {"recent": [{"id": i.id, "dataset": f"{i.dataset_name}@{i.dataset_version}", "status": i.status,
                                  "provenance": i.provenance, "created_at": i.created_at} for i in imports],
                      "failed_in_range": failed_imports},
        "drift_monitoring": drift_status(db),
        "top_sources": top(Event.source),
        "top_destinations": top(Event.destination),
        "recent_alert_ids": [a.id for a in recent],
        "definitions": DEFINITIONS,
    }


BUCKETS = {"minute": ("%Y-%m-%dT%H:%M:00", "minute"), "hour": ("%Y-%m-%dT%H:00:00", "hour"), "day": ("%Y-%m-%dT00:00:00", "day")}


def timeline(db: Session, *, import_id: int | None = None, model_version_id: int | None = None,
             bucket: str = "hour", since: datetime | None = None, until: datetime | None = None) -> dict[str, Any]:
    """Events per time bucket (by event timestamp), split by the model's verdict.

    ``suspicious`` / ``not_flagged`` count events with an OK prediction from the chosen
    model version (default: every prediction); ``unscored`` counts events without one.
    Events without a parseable timestamp are reported separately, not dropped silently.
    """
    from sqlalchemy import and_, case, literal_column

    if bucket not in BUCKETS:
        raise ValueError(f"bucket must be one of {sorted(BUCKETS)}")
    fmt, pg_unit = BUCKETS[bucket]
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        b = func.to_char(func.date_trunc(pg_unit, func.timezone("UTC", Event.occurred_at)),
                         literal_column("'YYYY-MM-DD\"T\"HH24:MI:SS'"))
    else:
        b = func.strftime(fmt, Event.occurred_at)
    join_cond = and_(Prediction.event_id == Event.id, Prediction.status == "ok")
    if model_version_id:
        join_cond = and_(join_cond, Prediction.model_version_id == model_version_id)
    q = (select(b.label("bucket"), func.count(func.distinct(Event.id)).label("events"),
                func.count(func.distinct(case((Prediction.is_suspicious.is_(True), Event.id)))).label("suspicious"),
                func.count(func.distinct(case((Prediction.is_suspicious.is_(False), Event.id)))).label("not_flagged"))
         .select_from(Event).outerjoin(Prediction, join_cond).where(Event.occurred_at.is_not(None)))
    if import_id:
        q = q.where(Event.import_id == import_id)
    if since:
        q = q.where(Event.occurred_at >= since)
    if until:
        q = q.where(Event.occurred_at < until)
    rows = db.execute(q.group_by(b).order_by(b)).all()
    no_ts = select(func.count(Event.id)).where(Event.occurred_at.is_(None))
    if import_id:
        no_ts = no_ts.where(Event.import_id == import_id)
    points = [{"bucket_start": f"{r.bucket}Z", "events": r.events, "suspicious": r.suspicious,
               "not_flagged": r.not_flagged, "unscored": r.events - r.suspicious - r.not_flagged} for r in rows]
    return {"bucket": bucket, "basis": "event timestamp (UTC)", "points": points,
            "events_without_timestamp": db.scalar(no_ts) or 0,
            "definitions": {"suspicious": DEFINITIONS["suspicious_predictions"],
                            "not_flagged": "Events whose prediction is the benign class (status ok).",
                            "unscored": "Events with no successful prediction from the selected model."}}
