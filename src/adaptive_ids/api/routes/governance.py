from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from ...db.models import User
from ...governance import protocol as protocol_module
from ...services import audit
from ...services import governance as svc
from ...services import registry
from ..deps import allow, client_ip, get_db
from ..schemas import EvaluationCreate, EvaluationDetail, EvaluationOut, ModelDetail

router = APIRouter(tags=["governance"])


@router.get("/governance/protocol")
def protocol(request: Request, _: User = Depends(allow("config.read"))):
    """The protocol every candidate is evaluated under, and its documented rules."""
    return {"protocol": svc.current_protocol(request.app.state.settings).to_dict(), "rules": protocol_module.__doc__}


@router.get("/evaluations", response_model=list[EvaluationOut])
def list_all(_: User = Depends(allow("models.read")), db: Session = Depends(get_db)):
    return svc.list_evaluations(db)


@router.get("/models/{model_id}/evaluations", response_model=list[EvaluationOut])
def list_for_model(model_id: int, _: User = Depends(allow("models.read")), db: Session = Depends(get_db)):
    registry.get(db, model_id)
    return svc.list_evaluations(db, model_id)


@router.post("/models/{model_id}/evaluations", response_model=EvaluationOut, status_code=202)
def create(model_id: int, body: EvaluationCreate, request: Request, background: BackgroundTasks,
           admin: User = Depends(allow("models.manage")), db: Session = Depends(get_db)):
    """Evaluate a candidate against the active model on a labelled import (runs in the background)."""
    st = request.app.state
    ev = svc.start_evaluation(db, model_id, body.import_id, st.settings, admin, client_ip(request))
    db.commit()
    background.add_task(svc.run_evaluation, st.session_factory, ev.id, st.model_cache)
    return ev


@router.get("/evaluations/{evaluation_id}", response_model=EvaluationDetail)
def get_one(evaluation_id: int, _: User = Depends(allow("models.read")), db: Session = Depends(get_db)):
    return svc.get_evaluation(db, evaluation_id)


@router.get("/evaluations/{evaluation_id}/report.md", response_class=PlainTextResponse)
def report(evaluation_id: int, request: Request, user: User = Depends(allow("data.export")), db: Session = Depends(get_db)):
    ev = svc.get_evaluation(db, evaluation_id)
    text = svc.report_markdown(db, ev)
    audit.record(db, "model.evaluation_report_export", actor=user, entity_type="model_evaluation", entity_id=ev.id,
                 client_ip=client_ip(request))
    return PlainTextResponse(text, media_type="text/markdown",
                             headers={"Content-Disposition": f"attachment; filename=evaluation-{ev.id}.md"})


@router.post("/models/{model_id}/verify-restore", response_model=ModelDetail)
def verify_restore(model_id: int, request: Request, admin: User = Depends(allow("models.manage")),
                   db: Session = Depends(get_db)):
    """Re-load the artifact from disk and replay its recorded sample; the result is stored and audited."""
    mv = registry.get(db, model_id)
    svc.record_restore_check(db, mv, admin, client_ip(request))
    return mv
