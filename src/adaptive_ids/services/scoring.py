"""Score an import's events with a model version and raise alerts for suspicious predictions.

A prediction is *suspicious* when it was produced successfully and its class is
not the model's benign label (or, for a thresholded binary model, equals the
positive class). Suspicious is not the same as a confirmed attack: alerts start
as ``new`` and only analysts change that.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..db.models import Alert, AlertStatusChange, DatasetImport, Event, ModelVersion, Prediction, ScoringRun, User, utcnow
from ..db.session import session_scope
from ..detection import ArtifactTrustError, InferenceError, Predictor, load_verified_artifact
from ..evaluation import classification_metrics
from ..preprocessing import PreprocessingError, Preprocessor
from ..settings import Settings
from . import audit
from .errors import Conflict, InvalidRequest, NotFound
from .imports import get_schema
from .severity import SeverityRules

log = logging.getLogger(__name__)
SCORE_BATCH = 5000


class ModelCache:
    """Keeps hash-verified models in memory, keyed by version and artifact hash."""

    def __init__(self) -> None:
        self._models: dict[tuple[str, str], Any] = {}
        self._lock = threading.Lock()

    def get(self, mv: ModelVersion) -> Any:
        key = (mv.version_id, mv.artifact_sha256)
        with self._lock:
            if key not in self._models:
                model, _ = load_verified_artifact(mv.artifact_path, mv.artifact_sha256, mv.artifact_format,
                                                  label=mv.version_id)
                self._models[key] = model
            return self._models[key]


def is_suspicious(mv: ModelVersion, predicted_class: Any, status: str) -> bool:
    if status != "ok" or predicted_class is None:
        return False
    if mv.threshold is not None and mv.positive_class is not None:
        return str(predicted_class) == mv.positive_class
    return str(predicted_class) != mv.benign_label


def group_key(import_id: int, predicted_class: str, source: str | None, destination: str | None) -> str:
    return f"{import_id}|{predicted_class}|{source or '-'}|{destination or '-'}"[:600]


def start_scoring(
    db: Session, import_id: int, model_version_id: int | None, settings: Settings, actor: User, client_ip: str | None = None
) -> ScoringRun:
    imp = db.get(DatasetImport, import_id)
    if imp is None:
        raise NotFound("import not found")
    if imp.status != "completed":
        raise Conflict(f"only completed imports can be scored (status is {imp.status})")
    if model_version_id is None:
        mv = db.scalar(select(ModelVersion).where(ModelVersion.status == "active"))
        if mv is None:
            raise Conflict("no active model; approve and activate a model version first")
    else:
        mv = db.get(ModelVersion, model_version_id)
        if mv is None:
            raise NotFound("model version not found")
        if mv.status not in ("active", "approved"):
            raise Conflict("only approved or active model versions can score data")
    model_feats = sorted(mv.feature_schema["features"], key=lambda f: f["name"])
    data_feats = sorted(get_schema(settings, imp.schema_id).to_dict()["features"], key=lambda f: f["name"])
    if [f["name"] for f in model_feats] != [f["name"] for f in data_feats]:
        raise InvalidRequest(
            f"import schema {imp.schema_id} does not provide the features model {mv.version_id} was trained on"
        )
    existing = db.scalar(select(ScoringRun).where(
        ScoringRun.import_id == import_id, ScoringRun.model_version_id == mv.id,
        ScoringRun.status.in_(("queued", "running", "completed"))))
    if existing:
        raise Conflict(f"import {import_id} already scored (or being scored) by {mv.version_id} in run {existing.id}")
    run = ScoringRun(import_id=import_id, model_version_id=mv.id, status="queued", created_by_id=actor.id)
    db.add(run)
    db.flush()
    audit.record(db, "scoring.start", actor=actor, entity_type="scoring_run", entity_id=run.id,
                 details={"import_id": import_id, "model_version": mv.version_id}, client_ip=client_ip)
    return run


def run_scoring(factory: sessionmaker[Session], run_id: int, rules: SeverityRules, cache: ModelCache) -> None:
    """Execute a queued scoring run in one transaction; failures leave no partial predictions."""
    t0 = time.perf_counter()
    with session_scope(factory) as db:
        run = db.get(ScoringRun, run_id)
        if run is None or run.status != "queued":
            return
        run.status = "running"
        run.started_at = utcnow()
    try:
        with session_scope(factory) as db:
            run = db.get(ScoringRun, run_id)
            mv = db.get(ModelVersion, run.model_version_id)
            pp = Preprocessor.from_dict(mv.preprocessor)
            predictor = Predictor(cache.get(mv), mv.version_id, pp, positive_class=mv.positive_class,
                                  threshold=mv.threshold)
            feats = pp.schema.feature_names
            total = scored = rejected = suspicious = alerts = 0
            y_true: list[str] = []
            y_pred: list[str] = []
            last_id = 0
            while True:
                events = list(db.scalars(select(Event).where(Event.import_id == run.import_id, Event.id > last_id)
                                         .order_by(Event.id).limit(SCORE_BATCH)))
                if not events:
                    break
                last_id = events[-1].id
                frame = pd.DataFrame([{f: (np.nan if e.features.get(f) is None else e.features.get(f)) for f in feats}
                                      for e in events]).astype("float64")
                out = predictor.predict(frame, event_ids=[e.id for e in events])
                preds = []
                for e, row in zip(events, out.to_dict(orient="records")):
                    sus = is_suspicious(mv, row["predicted_class"], row["status"])
                    score = None if row["score"] is None or pd.isna(row["score"]) else float(row["score"])
                    p = Prediction(
                        scoring_run_id=run.id, event_id=e.id, model_version_id=mv.id,
                        predicted_class=None if row["predicted_class"] is None else str(row["predicted_class"]),
                        score=score, score_kind=row["score_kind"], threshold=row["threshold"],
                        decision_rule=row["decision_rule"], preprocessing_version=row["preprocessing_version"],
                        inferred_at=utcnow(), status=row["status"], error=row["error"], is_suspicious=sus,
                    )
                    preds.append((e, p))
                    total += 1
                    if row["status"] == "ok":
                        scored += 1
                        if e.dataset_label is not None:
                            y_true.append(e.dataset_label)
                            y_pred.append(p.predicted_class)
                    else:
                        rejected += 1
                db.add_all([p for _, p in preds])
                db.flush()
                for e, p in preds:
                    if not p.is_suspicious:
                        continue
                    suspicious += 1
                    sev, rule_id = rules.evaluate(p.predicted_class, p.score)
                    alert = Alert(prediction_id=p.id, event_id=e.id, model_version_id=mv.id, import_id=run.import_id,
                                  predicted_class=p.predicted_class, score=p.score, severity=sev,
                                  severity_rule=f"{rules.version}:{rule_id}",
                                  group_key=group_key(run.import_id, p.predicted_class, e.source, e.destination),
                                  status="new")
                    db.add(alert)
                    alerts += 1
                db.flush()
            db.add_all([AlertStatusChange(alert_id=a.id, from_status=None, to_status="new", note="created by scoring run")
                        for a in db.scalars(select(Alert).join(Prediction, Alert.prediction_id == Prediction.id)
                                            .where(Prediction.scoring_run_id == run.id))])
            label_metrics = None
            if y_true:
                label_metrics = classification_metrics(y_true, y_pred, benign_label=mv.benign_label)
                label_metrics["basis"] = ("dataset-provided labels from the imported file; "
                                          "not analyst-confirmed outcomes")
            run.events_total, run.events_scored, run.events_rejected = total, scored, rejected
            run.suspicious, run.alerts_created = suspicious, alerts
            run.label_metrics = label_metrics
            run.severity_rules_version = rules.version
            run.status = "completed"
            run.completed_at = utcnow()
            run.duration_ms = (time.perf_counter() - t0) * 1000
    except (ArtifactTrustError, InferenceError, PreprocessingError) as exc:
        _fail(factory, run_id, str(exc), t0)
    except Exception:
        log.exception("scoring run %s failed", run_id)
        _fail(factory, run_id, "internal error during scoring (see server log)", t0)


def _fail(factory: sessionmaker[Session], run_id: int, message: str, t0: float) -> None:
    with session_scope(factory) as db:
        run = db.get(ScoringRun, run_id)
        if run:
            run.status = "failed"
            run.error = message
            run.completed_at = utcnow()
            run.duration_ms = (time.perf_counter() - t0) * 1000
