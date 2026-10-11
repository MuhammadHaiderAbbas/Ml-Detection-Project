from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ... import __version__
from ...db.models import AuditLog, User
from ...services import dashboard
from ..deps import current_user, get_db, require
from ..schemas import AuditOut, Page

router = APIRouter(tags=["system"])


@router.get("/health")
def health(request: Request, db: Session = Depends(get_db)):
    """Liveness plus database connectivity. No authentication; reveals no data."""
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
    except Exception:
        database = "unavailable"
    return {"status": "ok" if database == "ok" else "degraded", "version": __version__, "database": database}


@router.get("/dashboard/summary")
def summary(import_id: int | None = None, model_version_id: int | None = None, since: datetime | None = None,
            until: datetime | None = None, _: User = Depends(current_user), db: Session = Depends(get_db)):
    return dashboard.summary(db, import_id=import_id, model_version_id=model_version_id, since=since, until=until)


@router.get("/dashboard/timeline")
def timeline(import_id: int | None = None, model_version_id: int | None = None, bucket: str = "hour",
             since: datetime | None = None, until: datetime | None = None,
             _: User = Depends(current_user), db: Session = Depends(get_db)):
    from ...services.errors import InvalidRequest

    try:
        return dashboard.timeline(db, import_id=import_id, model_version_id=model_version_id, bucket=bucket,
                                  since=since, until=until)
    except ValueError as exc:
        raise InvalidRequest(str(exc)) from exc


@router.get("/severity-rules")
def severity_rules(request: Request, _: User = Depends(current_user)):
    return request.app.state.severity_rules.to_dict()


@router.get("/audit-logs", response_model=Page[AuditOut])
def audit_logs(action: str | None = None, actor_id: int | None = None, entity_type: str | None = None,
               entity_id: str | None = None, limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0),
               _: User = Depends(require("admin")), db: Session = Depends(get_db)):
    q = select(AuditLog)
    for col, val in ((AuditLog.action, action), (AuditLog.actor_id, actor_id),
                     (AuditLog.entity_type, entity_type), (AuditLog.entity_id, entity_id)):
        if val is not None:
            q = q.where(col == val)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    items = list(db.scalars(q.order_by(AuditLog.at.desc(), AuditLog.id.desc()).limit(limit).offset(offset)))
    return Page(items=items, total=total, limit=limit, offset=offset)
