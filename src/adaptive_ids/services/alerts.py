"""Alert lifecycle: New -> Investigating -> Resolved | False Positive (re-openable).

Every status change, assignment and note is an analyst action stored
separately from the automated prediction that created the alert.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from ..db.models import (
    Alert,
    AlertNote,
    AlertStatusChange,
    Event,
    Incident,
    ModelVersion,
    Prediction,
    User,
    utcnow,
)
from . import audit
from .errors import InvalidRequest, NotFound

STATUSES = ("new", "investigating", "resolved", "false_positive")
TRANSITIONS = {
    "new": {"investigating", "false_positive"},
    "investigating": {"resolved", "false_positive"},
    "resolved": {"investigating"},
    "false_positive": {"investigating"},
}
NOTE_REQUIRED = {"resolved", "false_positive"}
MAX_NOTE = 10_000


@dataclass
class AlertFilters:
    status: list[str] | None = None
    severity: list[str] | None = None
    import_id: int | None = None
    model_version_id: int | None = None
    assignee_id: int | None = None
    predicted_class: str | None = None
    group_key: str | None = None
    incident_id: int | None = None
    source: str | None = None
    destination: str | None = None
    since: datetime | None = None
    until: datetime | None = None


def _filtered(f: AlertFilters) -> Select:
    q = select(Alert)
    if f.source or f.destination:
        q = q.join(Event, Alert.event_id == Event.id)
        if f.source:
            q = q.where(Event.source == f.source)
        if f.destination:
            q = q.where(Event.destination == f.destination)
    if f.status:
        bad = set(f.status) - set(STATUSES)
        if bad:
            raise InvalidRequest(f"unknown status {sorted(bad)}")
        q = q.where(Alert.status.in_(f.status))
    if f.severity:
        q = q.where(Alert.severity.in_(f.severity))
    for col, val in ((Alert.import_id, f.import_id), (Alert.model_version_id, f.model_version_id),
                     (Alert.assignee_id, f.assignee_id), (Alert.predicted_class, f.predicted_class),
                     (Alert.group_key, f.group_key), (Alert.incident_id, f.incident_id)):
        if val is not None:
            q = q.where(col == val)
    if f.since:
        q = q.where(Alert.created_at >= f.since)
    if f.until:
        q = q.where(Alert.created_at < f.until)
    return q


def list_alerts(db: Session, f: AlertFilters, limit: int, offset: int) -> tuple[list[Alert], int]:
    q = _filtered(f)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    items = list(db.scalars(q.order_by(Alert.created_at.desc(), Alert.id.desc()).limit(limit).offset(offset)))
    return items, total


def groups(db: Session, f: AlertFilters, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
    sub = _filtered(f).subquery()
    q = (select(sub.c.group_key, sub.c.predicted_class, func.count().label("alerts"),
                func.max(sub.c.score).label("max_score"), func.min(sub.c.created_at).label("first_seen"),
                func.max(sub.c.created_at).label("last_seen"))
         .group_by(sub.c.group_key, sub.c.predicted_class))
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.execute(q.order_by(func.count().desc()).limit(limit).offset(offset)).all()
    out = []
    for r in rows:
        _, _, src, dst = (r.group_key.split("|") + ["", "", "", ""])[:4]
        out.append({"group_key": r.group_key, "predicted_class": r.predicted_class, "source": src, "destination": dst,
                    "alerts": r.alerts, "max_score": r.max_score, "first_seen": r.first_seen, "last_seen": r.last_seen})
    return out, total


def get(db: Session, alert_id: int) -> Alert:
    a = db.get(Alert, alert_id)
    if a is None:
        raise NotFound("alert not found")
    return a


def detail(db: Session, alert_id: int) -> dict[str, Any]:
    a = get(db, alert_id)
    event = db.get(Event, a.event_id)
    pred = db.get(Prediction, a.prediction_id)
    mv = db.get(ModelVersion, a.model_version_id)
    users = {u.id: u.username for u in db.scalars(select(User))}
    notes = list(db.scalars(select(AlertNote).where(AlertNote.alert_id == a.id).order_by(AlertNote.created_at, AlertNote.id)))
    hist = list(db.scalars(select(AlertStatusChange).where(AlertStatusChange.alert_id == a.id)
                           .order_by(AlertStatusChange.changed_at, AlertStatusChange.id)))
    related = list(db.scalars(select(Alert).where(Alert.group_key == a.group_key, Alert.id != a.id)
                              .order_by(Alert.created_at.desc()).limit(20)))
    return {
        "alert": a,
        "assignee": users.get(a.assignee_id),
        "event": event,
        "prediction": pred,
        "model": mv,
        "incident": db.get(Incident, a.incident_id) if a.incident_id else None,
        "notes": [(n, users.get(n.author_id)) for n in notes],
        "history": [(h, users.get(h.changed_by_id) if h.changed_by_id else "system") for h in hist],
        "related_alerts": related,
    }


def transition(db: Session, alert_id: int, to_status: str, actor: User, note: str | None, client_ip: str | None = None) -> Alert:
    a = get(db, alert_id)
    if to_status not in STATUSES:
        raise InvalidRequest(f"status must be one of {STATUSES}")
    if to_status not in TRANSITIONS[a.status]:
        raise InvalidRequest(f"cannot move an alert from {a.status} to {to_status}; "
                             f"allowed: {sorted(TRANSITIONS[a.status])}")
    note = (note or "").strip() or None
    if to_status in NOTE_REQUIRED and not note:
        raise InvalidRequest(f"a note explaining the decision is required to mark an alert {to_status}")
    if note and len(note) > MAX_NOTE:
        raise InvalidRequest("note is too long")
    db.add(AlertStatusChange(alert_id=a.id, from_status=a.status, to_status=to_status, changed_by_id=actor.id, note=note))
    old = a.status
    a.status = to_status
    a.updated_at = utcnow()
    if to_status == "investigating" and a.assignee_id is None:
        a.assignee_id = actor.id
    audit.record(db, "alert.status", actor=actor, entity_type="alert", entity_id=a.id,
                 details={"from": old, "to": to_status}, client_ip=client_ip)
    return a


def assign(db: Session, alert_id: int, assignee_id: int | None, actor: User, client_ip: str | None = None) -> Alert:
    a = get(db, alert_id)
    if assignee_id is not None:
        u = db.get(User, assignee_id)
        if u is None or not u.is_active:
            raise InvalidRequest("assignee must be an active user")
    a.assignee_id = assignee_id
    a.updated_at = utcnow()
    audit.record(db, "alert.assign", actor=actor, entity_type="alert", entity_id=a.id,
                 details={"assignee_id": assignee_id}, client_ip=client_ip)
    return a


def add_note(db: Session, alert_id: int, body: str, actor: User) -> AlertNote:
    a = get(db, alert_id)
    body = (body or "").strip()
    if not body or len(body) > MAX_NOTE:
        raise InvalidRequest(f"note must be 1-{MAX_NOTE} characters")
    n = AlertNote(alert_id=a.id, author_id=actor.id, body=body)
    db.add(n)
    a.updated_at = utcnow()
    db.flush()
    return n
