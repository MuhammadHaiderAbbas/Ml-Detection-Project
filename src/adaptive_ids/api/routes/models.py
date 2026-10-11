from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.models import ModelVersion, User
from ...services import registry as svc
from ..deps import client_ip, current_user, get_db, require
from ..schemas import ApproveBody, ModelDetail, ModelOut, ModelStatusChangeOut, ReasonBody, RegisterRun, RunOut

router = APIRouter(tags=["models"])


@router.get("/experiment-runs", response_model=list[RunOut])
def experiment_runs(request: Request, _: User = Depends(current_user), db: Session = Depends(get_db)):
    """Completed experiment runs on the server that could be registered as model versions."""
    base = Path(request.app.state.settings.runs_dir)
    registered = {r for (r,) in db.execute(select(ModelVersion.source_run))}
    out = []
    for d in sorted(base.glob("*/result.json"), reverse=True):
        try:
            r = json.loads(d.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        test = (r.get("metrics") or {}).get("test") or {}
        out.append(RunOut(run_name=d.parent.name, experiment_id=r.get("experiment_id"), provenance=r.get("provenance"),
                          model_version=(r.get("model") or {}).get("model_version"),
                          test_accuracy=test.get("accuracy"), registered=d.parent.name in registered))
    return out


@router.get("/models", response_model=list[ModelOut])
def list_models(_: User = Depends(current_user), db: Session = Depends(get_db)):
    return list(db.scalars(select(ModelVersion).order_by(ModelVersion.created_at.desc())))


@router.get("/models/active", response_model=ModelDetail | None)
def active(_: User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.get_active(db)


@router.get("/models/{model_id}", response_model=ModelDetail)
def get_model(model_id: int, _: User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.get(db, model_id)


@router.get("/models/{model_id}/history", response_model=list[ModelStatusChangeOut])
def model_history(model_id: int, _: User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.history(db, model_id)


@router.post("/models/register-run", response_model=ModelDetail, status_code=201)
def register(body: RegisterRun, request: Request, admin: User = Depends(require("admin")), db: Session = Depends(get_db)):
    return svc.register_from_run(db, body.run_name, request.app.state.settings, admin, client_ip(request))


@router.post("/models/{model_id}/approve", response_model=ModelDetail)
def approve(model_id: int, body: ApproveBody, request: Request, admin: User = Depends(require("admin")),
            db: Session = Depends(get_db)):
    """Approve a candidate that passed its evaluation (or, with ``override``, a justified exception)."""
    return svc.approve(db, model_id, admin, body.reason, request.app.state.settings,
                       evaluation_id=body.evaluation_id, override=body.override, client_ip=client_ip(request))


@router.post("/models/{model_id}/reject", response_model=ModelDetail)
def reject(model_id: int, body: ReasonBody, request: Request, admin: User = Depends(require("admin")),
           db: Session = Depends(get_db)):
    return svc.reject(db, model_id, admin, body.reason, client_ip(request))


@router.post("/models/{model_id}/activate", response_model=ModelDetail)
def activate(model_id: int, body: ReasonBody, request: Request, admin: User = Depends(require("admin")),
             db: Session = Depends(get_db)):
    """Activate an approved version, or roll back to a previously approved archived one."""
    return svc.activate(db, model_id, admin, body.reason, client_ip(request))
