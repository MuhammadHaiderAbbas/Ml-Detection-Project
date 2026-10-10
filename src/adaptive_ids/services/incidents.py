"""Incidents group related alerts and record the analyst's investigation and decision.

The *disposition* (confirmed_attack, benign, false_positive, inconclusive) is
the only place where a confirmed attack is recorded. It is always a human
decision. No blocking or other remediation is performed by the system.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import Alert, AlertStatusChange, Event, Incident, IncidentNote, User, utcnow
from . import audit
from .errors import Conflict, InvalidRequest, NotFound

STATUSES = ("open", "investigating", "closed")
DISPOSITIONS = ("undetermined", "confirmed_attack", "benign", "false_positive", "inconclusive")
NOTE_KINDS = ("note", "evidence")


def get(db: Session, incident_id: int) -> Incident:
    inc = db.get(Incident, incident_id)
    if inc is None:
        raise NotFound("incident not found")
    return inc


def _check_user(db: Session, user_id: int | None) -> None:
    if user_id is not None:
        u = db.get(User, user_id)
        if u is None or not u.is_active:
            raise InvalidRequest("owner must be an active user")


def create(db: Session, title: str, summary: str | None, alert_ids: list[int], owner_id: int | None,
           actor: User, client_ip: str | None = None) -> Incident:
    title = (title or "").strip()
    if not 1 <= len(title) <= 300:
        raise InvalidRequest("title must be 1-300 characters")
    _check_user(db, owner_id)
    inc = Incident(title=title, summary=summary, status="open", disposition="undetermined",
                   owner_id=owner_id if owner_id is not None else actor.id, created_by_id=actor.id)
    db.add(inc)
    db.flush()
    audit.record(db, "incident.create", actor=actor, entity_type="incident", entity_id=inc.id,
                 details={"title": title, "alert_ids": alert_ids}, client_ip=client_ip)
    if alert_ids:
        link_alerts(db, inc.id, alert_ids, actor, client_ip)
    return inc


def link_alerts(db: Session, incident_id: int, alert_ids: list[int], actor: User, client_ip: str | None = None) -> Incident:
    inc = get(db, incident_id)
    if inc.status == "closed":
        raise Conflict("cannot link alerts to a closed incident")
    alerts = list(db.scalars(select(Alert).where(Alert.id.in_(alert_ids))))
    missing = sorted(set(alert_ids) - {a.id for a in alerts})
    if missing:
        raise NotFound(f"alerts not found: {missing}")
    taken = [a.id for a in alerts if a.incident_id not in (None, inc.id)]
    if taken:
        raise Conflict(f"alerts already belong to another incident: {taken}")
    for a in alerts:
        a.incident_id = inc.id
        a.updated_at = utcnow()
    inc.updated_at = utcnow()
    audit.record(db, "incident.link_alerts", actor=actor, entity_type="incident", entity_id=inc.id,
                 details={"alert_ids": alert_ids}, client_ip=client_ip)
    return inc


def unlink_alert(db: Session, incident_id: int, alert_id: int, actor: User, client_ip: str | None = None) -> Incident:
    inc = get(db, incident_id)
    a = db.get(Alert, alert_id)
    if a is None or a.incident_id != inc.id:
        raise NotFound("alert is not linked to this incident")
    a.incident_id = None
    inc.updated_at = utcnow()
    audit.record(db, "incident.unlink_alert", actor=actor, entity_type="incident", entity_id=inc.id,
                 details={"alert_id": alert_id}, client_ip=client_ip)
    return inc


def update(db: Session, incident_id: int, changes: dict[str, Any], actor: User, client_ip: str | None = None) -> Incident:
    inc = get(db, incident_id)
    before = {"status": inc.status, "disposition": inc.disposition, "owner_id": inc.owner_id}
    if "title" in changes:
        title = (changes["title"] or "").strip()
        if not 1 <= len(title) <= 300:
            raise InvalidRequest("title must be 1-300 characters")
        inc.title = title
    if "summary" in changes:
        inc.summary = changes["summary"]
    if "owner_id" in changes:
        _check_user(db, changes["owner_id"])
        inc.owner_id = changes["owner_id"]
    if "disposition" in changes:
        disp = changes["disposition"]
        if disp not in DISPOSITIONS:
            raise InvalidRequest(f"disposition must be one of {DISPOSITIONS}")
        reason = (changes.get("decision_note") or "").strip()
        if disp != inc.disposition:
            if not reason:
                raise InvalidRequest("decision_note is required when changing the disposition")
            db.add(IncidentNote(incident_id=inc.id, author_id=actor.id, kind="decision",
                                body=f"Disposition {inc.disposition} -> {disp}: {reason}"))
            inc.disposition = disp
    if "status" in changes:
        st = changes["status"]
        if st not in STATUSES:
            raise InvalidRequest(f"status must be one of {STATUSES}")
        if st == "closed" and inc.disposition == "undetermined":
            raise InvalidRequest("set a disposition before closing an incident")
        inc.status = st
        inc.closed_at = utcnow() if st == "closed" else None
    inc.updated_at = utcnow()
    after = {"status": inc.status, "disposition": inc.disposition, "owner_id": inc.owner_id}
    audit.record(db, "incident.update", actor=actor, entity_type="incident", entity_id=inc.id,
                 details={"before": before, "after": after, "fields": sorted(changes)}, client_ip=client_ip)
    return inc


def add_note(db: Session, incident_id: int, body: str, kind: str, actor: User) -> IncidentNote:
    inc = get(db, incident_id)
    body = (body or "").strip()
    if kind not in NOTE_KINDS:
        raise InvalidRequest(f"kind must be one of {NOTE_KINDS} (decisions are recorded via the disposition)")
    if not body or len(body) > 10_000:
        raise InvalidRequest("note must be 1-10000 characters")
    n = IncidentNote(incident_id=inc.id, author_id=actor.id, kind=kind, body=body)
    db.add(n)
    inc.updated_at = utcnow()
    db.flush()
    return n


def list_incidents(db: Session, status: list[str] | None, disposition: str | None, limit: int, offset: int):
    q = select(Incident)
    if status:
        q = q.where(Incident.status.in_(status))
    if disposition:
        q = q.where(Incident.disposition == disposition)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    return list(db.scalars(q.order_by(Incident.updated_at.desc(), Incident.id.desc()).limit(limit).offset(offset))), total


def detail(db: Session, incident_id: int) -> dict[str, Any]:
    inc = get(db, incident_id)
    users = {u.id: u.username for u in db.scalars(select(User))}
    alerts = list(db.scalars(select(Alert).where(Alert.incident_id == inc.id).order_by(Alert.created_at)))
    events = {e.id: e for e in db.scalars(select(Event).where(Event.id.in_([a.event_id for a in alerts])))} if alerts else {}
    notes = list(db.scalars(select(IncidentNote).where(IncidentNote.incident_id == inc.id)
                            .order_by(IncidentNote.created_at, IncidentNote.id)))
    changes = list(db.scalars(select(AlertStatusChange).where(AlertStatusChange.alert_id.in_([a.id for a in alerts]))
                              .order_by(AlertStatusChange.changed_at))) if alerts else []
    timeline: list[dict[str, Any]] = []
    for a in alerts:
        e = events.get(a.event_id)
        if e is not None and e.occurred_at is not None:
            timeline.append({"at": e.occurred_at, "kind": "event", "actor": None,
                             "text": f"Event {e.event_key or e.id}: {e.source or '?'} -> {e.destination or '?'} "
                                     f"(alert {a.id}, predicted {a.predicted_class})"})
    for c in changes:
        if c.changed_by_id is None:
            continue
        timeline.append({"at": c.changed_at, "kind": "alert_status", "actor": users.get(c.changed_by_id),
                         "text": f"Alert {c.alert_id}: {c.from_status} -> {c.to_status}" + (f" — {c.note}" if c.note else "")})
    for n in notes:
        timeline.append({"at": n.created_at, "kind": n.kind, "actor": users.get(n.author_id), "text": n.body})
    timeline.sort(key=lambda t: t["at"])
    sources = sorted({e.source for e in events.values() if e.source})
    destinations = sorted({e.destination for e in events.values() if e.destination})
    return {"incident": inc, "owner": users.get(inc.owner_id), "alerts": alerts, "notes": [(n, users.get(n.author_id)) for n in notes],
            "timeline": timeline, "sources": sources, "destinations": destinations}


def export_markdown(db: Session, incident_id: int) -> str:
    d = detail(db, incident_id)
    inc = d["incident"]
    lines = [
        f"# Incident {inc.id}: {inc.title}", "",
        f"- Status: {inc.status}",
        f"- Disposition (analyst decision): {inc.disposition}",
        f"- Owner: {d['owner'] or '-'}",
        f"- Created: {inc.created_at.isoformat()}  Updated: {inc.updated_at.isoformat()}"
        + (f"  Closed: {inc.closed_at.isoformat()}" if inc.closed_at else ""),
        f"- Sources: {', '.join(d['sources']) or 'n/a'}",
        f"- Destinations: {', '.join(d['destinations']) or 'n/a'}", "",
        "## Summary", "", inc.summary or "_none_", "",
        "## Linked alerts (automated model output)", "",
        "| Alert | Predicted class | Score (uncalibrated) | Severity rule | Status |", "|---|---|---|---|---|",
    ]
    for a in d["alerts"]:
        score = "n/a" if a.score is None else f"{a.score:.3f}"
        lines.append(f"| {a.id} | {a.predicted_class} | {score} | {a.severity} ({a.severity_rule}) | {a.status} |")
    lines += ["", "## Timeline", ""]
    for t in d["timeline"]:
        lines.append(f"- {t['at'].isoformat()} [{t['kind']}]" + (f" {t['actor']}:" if t["actor"] else "") + f" {t['text']}")
    lines += ["", "> Model predictions are suspicions, not confirmations. Only the disposition above records an analyst decision.", ""]
    return "\n".join(lines)
