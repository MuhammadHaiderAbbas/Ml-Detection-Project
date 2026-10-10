from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...db.models import Event, Prediction, ScoringRun, User
from ...services import scoring as svc
from ...services.errors import NotFound
from ..deps import client_ip, current_user, get_db
from ..schemas import EventOut, EventWithPredictions, Page, PredictionOut, ScoreRequest, ScoringRunOut

router = APIRouter(tags=["scoring", "events"])


@router.post("/imports/{import_id}/score", response_model=ScoringRunOut, status_code=202)
def score(import_id: int, body: ScoreRequest, request: Request, background: BackgroundTasks,
          user: User = Depends(current_user), db: Session = Depends(get_db)):
    st = request.app.state
    run = svc.start_scoring(db, import_id, body.model_version_id, st.settings, user, client_ip(request))
    db.commit()
    background.add_task(svc.run_scoring, st.session_factory, run.id, st.severity_rules, st.model_cache)
    return run


@router.get("/scoring-runs", response_model=list[ScoringRunOut])
def scoring_runs(import_id: int | None = None, _: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(ScoringRun)
    if import_id is not None:
        q = q.where(ScoringRun.import_id == import_id)
    return list(db.scalars(q.order_by(ScoringRun.started_at.desc()).limit(200)))


@router.get("/scoring-runs/{run_id}", response_model=ScoringRunOut)
def scoring_run(run_id: int, _: User = Depends(current_user), db: Session = Depends(get_db)):
    run = db.get(ScoringRun, run_id)
    if run is None:
        raise NotFound("scoring run not found")
    return run


@router.get("/events", response_model=Page[EventOut])
def events(import_id: int | None = None, source: str | None = None, destination: str | None = None,
           suspicious_only: bool = False, limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
           _: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(Event)
    if import_id is not None:
        q = q.where(Event.import_id == import_id)
    if source:
        q = q.where(Event.source == source)
    if destination:
        q = q.where(Event.destination == destination)
    if suspicious_only:
        q = q.where(Event.id.in_(select(Prediction.event_id).where(Prediction.is_suspicious.is_(True))))
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    items = list(db.scalars(q.order_by(Event.id).limit(limit).offset(offset)))
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/events/{event_id}", response_model=EventWithPredictions)
def event(event_id: int, _: User = Depends(current_user), db: Session = Depends(get_db)):
    e = db.get(Event, event_id)
    if e is None:
        raise NotFound("event not found")
    preds = list(db.scalars(select(Prediction).where(Prediction.event_id == e.id).order_by(Prediction.inferred_at)))
    return EventWithPredictions(event=EventOut.model_validate(e), predictions=[PredictionOut.model_validate(p) for p in preds])
