from __future__ import annotations

import json

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...db.models import DatasetImport, User
from ...ingestion import IngestionError, preview_csv
from ...services import imports as svc
from ...services.errors import InvalidRequest
from ..deps import client_ip, current_user, get_db
from ..schemas import ImportOut, Page, PreviewOut, RejectedRowOut, SchemaOut

router = APIRouter(tags=["imports"])


@router.get("/schemas", response_model=list[SchemaOut])
def schemas(request: Request, _: User = Depends(current_user)):
    return [SchemaOut(schema_id=sid, name=s.name, version=s.version, status=s.status, n_features=len(s.features),
                      label_column=s.label_column, context_columns=s.all_context_columns, notes=s.notes)
            for sid, s in svc.list_schemas(request.app.state.settings).items()]


def _mapping(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    try:
        m = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InvalidRequest("column_mapping must be a JSON object") from exc
    if not isinstance(m, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in m.items()):
        raise InvalidRequest("column_mapping must map source column names to schema column names")
    return m


@router.post("/imports/preview", response_model=PreviewOut)
def preview(request: Request, file: UploadFile = File(...), schema_id: str = Form(...),
            column_mapping: str | None = Form(None), _: User = Depends(current_user)):
    settings = request.app.state.settings
    schema = svc.get_schema(settings, schema_id)
    path, _size = svc.store_upload(file.file, file.filename or "", settings)
    try:
        return preview_csv(path, schema, column_mapping=_mapping(column_mapping), n_rows=20)
    except (IngestionError, ValueError) as exc:
        raise InvalidRequest(f"could not read the file: {exc}") from exc
    finally:
        path.unlink(missing_ok=True)


@router.post("/imports", response_model=ImportOut, status_code=202)
def create_import(
    request: Request,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    schema_id: str = Form(...),
    dataset_name: str = Form(...),
    dataset_version: str = Form(...),
    provenance: str = Form(...),
    data_source: str | None = Form(None),
    column_mapping: str | None = Form(None),
    duplicate_policy: str = Form("keep"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    settings = request.app.state.settings
    schema = svc.get_schema(settings, schema_id)
    mapping = _mapping(column_mapping)
    path, _size = svc.store_upload(file.file, file.filename or "", settings)
    try:
        rec = svc.create_import(db, stored_path=path, original_filename=file.filename or "upload.csv", schema=schema,
                                dataset_name=dataset_name, dataset_version=dataset_version, provenance=provenance,
                                data_source=data_source, column_mapping=mapping, duplicate_policy=duplicate_policy,
                                actor=user, client_ip=client_ip(request))
        db.commit()
    except Exception:
        path.unlink(missing_ok=True)
        raise
    background.add_task(svc.run_import, request.app.state.session_factory, rec.id, settings, request.app.state.cancels)
    return rec


@router.get("/imports", response_model=Page[ImportOut])
def list_imports(status: str | None = None, limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
                 _: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(DatasetImport)
    if status:
        q = q.where(DatasetImport.status == status)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    items = list(db.scalars(q.order_by(DatasetImport.created_at.desc(), DatasetImport.id.desc()).limit(limit).offset(offset)))
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/imports/{import_id}", response_model=ImportOut)
def get_import(import_id: int, _: User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.get_import(db, import_id)


@router.get("/imports/{import_id}/rejected-rows", response_model=Page[RejectedRowOut])
def rejected(import_id: int, limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0),
             _: User = Depends(current_user), db: Session = Depends(get_db)):
    rows, total = svc.rejected_rows(db, import_id, limit, offset)
    return Page(items=rows, total=total, limit=limit, offset=offset)


@router.post("/imports/{import_id}/cancel", response_model=ImportOut)
def cancel(import_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.cancel_import(db, import_id, request.app.state.cancels, user, client_ip(request))
