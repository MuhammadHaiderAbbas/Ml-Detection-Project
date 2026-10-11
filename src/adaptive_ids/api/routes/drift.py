from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...db.models import DriftAnalysis, User
from ...drift import DriftConfig
from ...services import audit
from ...services import drift as svc
from ..deps import client_ip, current_user, get_db
from ..schemas import (
    DriftAnalysisCreate,
    DriftAnalysisDetail,
    DriftAnalysisOut,
    DriftEventDetail,
    DriftEventNoteOut,
    DriftEventOut,
    DriftStatusChange,
    DriftWindowOut,
    NoteBody,
    Page,
)

router = APIRouter(prefix="/drift", tags=["drift"])


@router.get("/config")
def default_config(_: User = Depends(current_user)):
    from ...drift import config as cfg_module

    return {"defaults": DriftConfig().to_dict(), "rules": cfg_module.__doc__}


@router.post("/analyses", response_model=DriftAnalysisOut, status_code=202)
def create(body: DriftAnalysisCreate, request: Request, background: BackgroundTasks, user: User = Depends(current_user),
           db: Session = Depends(get_db)):
    payload = body.model_dump(mode="json")
    a = svc.start_analysis(db, payload, request.app.state.settings, user, client_ip(request))
    db.commit()
    background.add_task(svc.run_analysis, request.app.state.session_factory, a.id)
    return a


@router.get("/analyses", response_model=Page[DriftAnalysisOut])
def list_analyses(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), _: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    total = db.scalar(select(func.count(DriftAnalysis.id))) or 0
    items = list(db.scalars(select(DriftAnalysis).order_by(DriftAnalysis.created_at.desc(), DriftAnalysis.id.desc()).limit(limit).offset(offset)))
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/analyses/{analysis_id}", response_model=DriftAnalysisDetail)
def get_analysis(analysis_id: int, _: User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.get_analysis(db, analysis_id)


@router.get("/analyses/{analysis_id}/windows", response_model=list[DriftWindowOut])
def get_windows(analysis_id: int, _: User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.windows(db, analysis_id)


@router.get("/analyses/{analysis_id}/report.md", response_class=PlainTextResponse)
def report(analysis_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    text = svc.report_markdown(db, analysis_id)
    audit.record(db, "drift.export", actor=user, entity_type="drift_analysis", entity_id=analysis_id,
                 details={"format": "markdown"}, client_ip=client_ip(request))
    return PlainTextResponse(text, media_type="text/markdown",
                             headers={"Content-Disposition": f"attachment; filename=drift-report-{analysis_id}.md"})


@router.get("/analyses/{analysis_id}/windows.csv", response_class=PlainTextResponse)
def windows_csv(analysis_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    text = svc.windows_csv(db, analysis_id)
    audit.record(db, "drift.export", actor=user, entity_type="drift_analysis", entity_id=analysis_id,
                 details={"format": "csv"}, client_ip=client_ip(request))
    return PlainTextResponse(text, media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename=drift-windows-{analysis_id}.csv"})


@router.get("/events", response_model=Page[DriftEventOut])
def events(status: list[str] | None = Query(None), drift_type: str | None = None, analysis_id: int | None = None,
           limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0), _: User = Depends(current_user),
           db: Session = Depends(get_db)):
    items, total = svc.list_events(db, status=status, drift_type=drift_type, analysis_id=analysis_id, limit=limit, offset=offset)
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/events/{event_id}", response_model=DriftEventDetail)
def event(event_id: int, _: User = Depends(current_user), db: Session = Depends(get_db)):
    e = svc.get_event(db, event_id)
    return DriftEventDetail(event=DriftEventOut.model_validate(e), notes=[
        DriftEventNoteOut(id=n.id, author=a, kind=n.kind, body=n.body, created_at=n.created_at) for n, a in svc.event_notes(db, e.id)])


@router.post("/events/{event_id}/status", response_model=DriftEventOut)
def event_status(event_id: int, body: DriftStatusChange, request: Request, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    return svc.transition_event(db, event_id, body.status, body.note, user, client_ip(request))


@router.post("/events/{event_id}/notes", response_model=DriftEventNoteOut, status_code=201)
def event_note(event_id: int, body: NoteBody, user: User = Depends(current_user), db: Session = Depends(get_db)):
    n = svc.add_event_note(db, event_id, body.body, user)
    return DriftEventNoteOut(id=n.id, author=user.username, kind=n.kind, body=n.body, created_at=n.created_at)
