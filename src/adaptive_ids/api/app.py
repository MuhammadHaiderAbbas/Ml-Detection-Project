"""FastAPI application factory."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .. import __version__
from ..db import make_engine, make_session_factory
from ..services.errors import ServiceError, TooManyRequests
from ..services.imports import CancelRegistry
from ..services.scoring import ModelCache
from ..services.severity import SeverityRules
from ..settings import Settings
from .routes import alerts, auth, drift, governance, imports, incidents, models, scoring, system

log = logging.getLogger("adaptive_ids.api")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(
        title="Adaptive IDS API",
        version=__version__,
        description=(
            "Network anomaly detection research platform. Predictions are suspicions, not confirmed attacks; "
            "model scores are uncalibrated unless stated."
        ),
    )
    engine = make_engine(settings.database_url)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.severity_rules = SeverityRules.load(settings.severity_rules_path)
    app.state.cancels = CancelRegistry()
    app.state.model_cache = ModelCache()

    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_credentials=False,
                       allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type"])

    @app.exception_handler(ServiceError)
    async def service_error(_: Request, exc: ServiceError):
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        if isinstance(exc, TooManyRequests):
            headers = {"Retry-After": str(exc.retry_after_s)}
        return JSONResponse({"detail": exc.message}, status_code=exc.status_code, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        errors = [{"loc": e.get("loc"), "msg": e.get("msg")} for e in exc.errors()]  # never echo submitted values
        return JSONResponse({"detail": "invalid request", "errors": errors}, status_code=422)

    @app.exception_handler(Exception)
    async def unexpected(_: Request, exc: Exception):
        ref = uuid.uuid4().hex[:12]
        log.exception("unhandled error ref=%s", ref)
        return JSONResponse({"detail": "internal server error", "reference": ref}, status_code=500)

    for r in (system, auth, imports, models, governance, scoring, alerts, incidents, drift):
        app.include_router(r.router, prefix="/api")
    if settings.web_dist_dir is not None:
        _mount_web(app, settings.web_dist_dir)
    return app


def _mount_web(app: FastAPI, dist: Path) -> None:
    """Serve the built React app (apps/web/dist); unknown non-API paths fall back to index.html."""
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    dist = dist.resolve()
    index = dist / "index.html"
    if not index.is_file():
        raise RuntimeError(f"web build not found at {dist}; run `npm run build` in apps/web")
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse({"detail": "not found"}, status_code=404)
        candidate = (dist / path).resolve()
        if path and dist in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)
