from __future__ import annotations

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ...db.models import User
from ...services import alerts as svc
from ...textsafety import csv_cell
from ..deps import allow, client_ip, get_db
from ..schemas import (
    AlertDetail,
    AlertGroupOut,
    AlertHistoryOut,
    AlertNoteOut,
    AlertOut,
    AssignBody,
    EventOut,
    ModelOut,
    NoteBody,
    Page,
    PredictionOut,
    StatusChange,
)

router = APIRouter(tags=["alerts"])


def filters(
    status: list[str] | None = Query(None), severity: list[str] | None = Query(None), import_id: int | None = None,
    model_version_id: int | None = None, assignee_id: int | None = None, predicted_class: str | None = None,
    group_key: str | None = None, incident_id: int | None = None, source: str | None = None,
    destination: str | None = None, since: datetime | None = None, until: datetime | None = None,
) -> svc.AlertFilters:
    return svc.AlertFilters(status=status, severity=severity, import_id=import_id, model_version_id=model_version_id,
                            assignee_id=assignee_id, predicted_class=predicted_class, group_key=group_key,
                            incident_id=incident_id, source=source, destination=destination, since=since, until=until)


@router.get("/alerts", response_model=Page[AlertOut])
def list_alerts(f: svc.AlertFilters = Depends(filters), limit: int = Query(50, ge=1, le=500),
                offset: int = Query(0, ge=0), _: User = Depends(allow("alerts.read")), db: Session = Depends(get_db)):
    items, total = svc.list_alerts(db, f, limit, offset)
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/alerts/groups", response_model=Page[AlertGroupOut])
def alert_groups(f: svc.AlertFilters = Depends(filters), limit: int = Query(50, ge=1, le=500),
                 offset: int = Query(0, ge=0), _: User = Depends(allow("alerts.read")), db: Session = Depends(get_db)):
    items, total = svc.groups(db, f, limit, offset)
    return Page(items=items, total=total, limit=limit, offset=offset)


_cell = csv_cell  # spreadsheet formula-injection guard


@router.get("/alerts/export.csv")
def export(request: Request, f: svc.AlertFilters = Depends(filters), user: User = Depends(allow("data.export")),
           db: Session = Depends(get_db)):
    items, total = svc.list_alerts(db, f, limit=100_000, offset=0)
    from ...services import audit

    audit.record(db, "alert.export", actor=user, details={"rows": len(items)}, client_ip=client_ip(request))
    buf = io.StringIO()
    w = csv.writer(buf)
    cols = ["id", "created_at", "status", "severity", "severity_rule", "predicted_class", "score",
            "model_version_id", "import_id", "event_id", "group_key", "assignee_id", "incident_id"]
    w.writerow(cols)
    for a in items:
        w.writerow([_cell(getattr(a, c).isoformat() if c == "created_at" else getattr(a, c)) for c in cols])
    w.writerow([])
    w.writerow(["# Alerts are model suspicions; scores are uncalibrated; severity is a triage priority, not a verified severity."])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=alerts.csv"})


@router.get("/alerts/{alert_id}", response_model=AlertDetail)
def alert_detail(alert_id: int, _: User = Depends(allow("alerts.read")), db: Session = Depends(get_db)):
    d = svc.detail(db, alert_id)
    return AlertDetail(
        alert=AlertOut.model_validate(d["alert"]), assignee=d["assignee"], event=EventOut.model_validate(d["event"]),
        prediction=PredictionOut.model_validate(d["prediction"]), model=ModelOut.model_validate(d["model"]),
        incident_id=d["incident"].id if d["incident"] else None,
        notes=[AlertNoteOut(id=n.id, author=a, body=n.body, created_at=n.created_at) for n, a in d["notes"]],
        history=[AlertHistoryOut(from_status=h.from_status, to_status=h.to_status, changed_by=by,
                                 changed_at=h.changed_at, note=h.note) for h, by in d["history"]],
        related_alerts=[AlertOut.model_validate(r) for r in d["related_alerts"]],
    )


@router.post("/alerts/{alert_id}/status", response_model=AlertOut)
def change_status(alert_id: int, body: StatusChange, request: Request, user: User = Depends(allow("alerts.write")),
                  db: Session = Depends(get_db)):
    return svc.transition(db, alert_id, body.status, user, body.note, client_ip(request))


@router.post("/alerts/{alert_id}/assign", response_model=AlertOut)
def assign(alert_id: int, body: AssignBody, request: Request, user: User = Depends(allow("alerts.write")),
           db: Session = Depends(get_db)):
    return svc.assign(db, alert_id, body.assignee_id, user, client_ip(request))


@router.post("/alerts/{alert_id}/notes", response_model=AlertNoteOut, status_code=201)
def add_note(alert_id: int, body: NoteBody, user: User = Depends(allow("alerts.write")), db: Session = Depends(get_db)):
    n = svc.add_note(db, alert_id, body.body, user)
    return AlertNoteOut(id=n.id, author=user.username, body=n.body, created_at=n.created_at)
