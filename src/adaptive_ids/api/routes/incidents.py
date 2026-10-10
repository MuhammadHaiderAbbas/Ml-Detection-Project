from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from ...db.models import User
from ...services import incidents as svc
from ..deps import client_ip, current_user, get_db
from ..schemas import (
    AlertOut,
    IncidentCreate,
    IncidentDetail,
    IncidentNoteBody,
    IncidentNoteOut,
    IncidentOut,
    IncidentUpdate,
    LinkAlerts,
    Page,
    TimelineItem,
)

router = APIRouter(tags=["incidents"])


def _detail(db: Session, incident_id: int) -> IncidentDetail:
    d = svc.detail(db, incident_id)
    return IncidentDetail(
        incident=IncidentOut.model_validate(d["incident"]), owner=d["owner"],
        alerts=[AlertOut.model_validate(a) for a in d["alerts"]],
        notes=[IncidentNoteOut(id=n.id, author=a, kind=n.kind, body=n.body, created_at=n.created_at) for n, a in d["notes"]],
        timeline=[TimelineItem(**t) for t in d["timeline"]], sources=d["sources"], destinations=d["destinations"],
    )


@router.get("/incidents", response_model=Page[IncidentOut])
def list_incidents(status: list[str] | None = Query(None), disposition: str | None = None,
                   limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
                   _: User = Depends(current_user), db: Session = Depends(get_db)):
    items, total = svc.list_incidents(db, status, disposition, limit, offset)
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.post("/incidents", response_model=IncidentDetail, status_code=201)
def create(body: IncidentCreate, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    inc = svc.create(db, body.title, body.summary, body.alert_ids, body.owner_id, user, client_ip(request))
    db.flush()
    return _detail(db, inc.id)


@router.get("/incidents/{incident_id}", response_model=IncidentDetail)
def get_incident(incident_id: int, _: User = Depends(current_user), db: Session = Depends(get_db)):
    return _detail(db, incident_id)


@router.patch("/incidents/{incident_id}", response_model=IncidentDetail)
def update(incident_id: int, body: IncidentUpdate, request: Request, user: User = Depends(current_user),
           db: Session = Depends(get_db)):
    svc.update(db, incident_id, body.model_dump(exclude_unset=True), user, client_ip(request))
    db.flush()
    return _detail(db, incident_id)


@router.post("/incidents/{incident_id}/alerts", response_model=IncidentDetail)
def link(incident_id: int, body: LinkAlerts, request: Request, user: User = Depends(current_user),
         db: Session = Depends(get_db)):
    svc.link_alerts(db, incident_id, body.alert_ids, user, client_ip(request))
    db.flush()
    return _detail(db, incident_id)


@router.delete("/incidents/{incident_id}/alerts/{alert_id}", response_model=IncidentDetail)
def unlink(incident_id: int, alert_id: int, request: Request, user: User = Depends(current_user),
           db: Session = Depends(get_db)):
    svc.unlink_alert(db, incident_id, alert_id, user, client_ip(request))
    db.flush()
    return _detail(db, incident_id)


@router.post("/incidents/{incident_id}/notes", response_model=IncidentNoteOut, status_code=201)
def add_note(incident_id: int, body: IncidentNoteBody, user: User = Depends(current_user), db: Session = Depends(get_db)):
    n = svc.add_note(db, incident_id, body.body, body.kind, user)
    return IncidentNoteOut(id=n.id, author=user.username, kind=n.kind, body=n.body, created_at=n.created_at)


@router.get("/incidents/{incident_id}/export.md", response_class=PlainTextResponse)
def export(incident_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from ...services import audit

    text = svc.export_markdown(db, incident_id)
    audit.record(db, "incident.export", actor=user, entity_type="incident", entity_id=incident_id,
                 client_ip=client_ip(request))
    return PlainTextResponse(text, media_type="text/markdown",
                             headers={"Content-Disposition": f"attachment; filename=incident-{incident_id}.md"})
