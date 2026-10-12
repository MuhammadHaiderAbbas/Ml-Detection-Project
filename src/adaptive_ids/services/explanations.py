"""Explanations for stored predictions.

An explanation is only produced when it provably belongs to the prediction it describes:

1. the model artifact is loaded through the hash-verified cache;
2. the stored preprocessing state rebuilds to the version the prediction recorded;
3. the event is re-scored and must reproduce the stored class and score exactly
   (score within :data:`SCORE_TOLERANCE`);
4. SHAP's contributions must add up to the model's own output (see ``explainability``).

If any step fails, the request fails with a reason; nothing is estimated in its place.
The first successful explanation is stored, so later reviews see the same attribution.
"""

from __future__ import annotations

import random
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Alert, Event, ModelVersion, Prediction, PredictionExplanation
from ..detection import ArtifactTrustError, InferenceError, Predictor
from ..explainability import ExplanationError, explain_rows, supports
from ..preprocessing import PreprocessingError, Preprocessor
from .errors import Conflict, NotFound
from .scoring import ModelCache

SCORE_TOLERANCE = 1e-9


def _unavailable(reason: str) -> dict[str, Any]:
    return {"available": False, "reason": reason}


def _out(row: PredictionExplanation, event: Event) -> dict[str, Any]:
    contributions = [{**c, "raw_value": event.features.get(c["feature"])} for c in row.contributions]
    return {
        "available": True, "reason": None, "prediction_id": row.prediction_id, "method": row.method,
        "library": row.library, "output_space": row.output_space, "target_class": row.target_class,
        "base_value": row.base_value, "model_output": row.model_output, "additivity_error": row.additivity_error,
        "artifact_sha256": row.artifact_sha256, "preprocessing_version": row.preprocessing_version,
        "contributions": contributions, "limitations": row.limitations, "computed_at": row.computed_at,
    }


def for_alert(db: Session, alert_id: int, cache: ModelCache) -> dict[str, Any]:
    a = db.get(Alert, alert_id)
    if a is None:
        raise NotFound(f"alert {alert_id} not found")
    return for_prediction(db, a.prediction_id, cache)


def _model_and_preprocessing(mv: ModelVersion, cache: ModelCache) -> tuple[Any, Preprocessor] | str:
    """The verified model and its preprocessing, or the reason the model can't be explained."""
    try:
        model = cache.get(mv)
    except ArtifactTrustError as exc:
        raise Conflict(f"cannot explain: the model artifact failed verification ({exc})") from exc
    ok, why = supports(model)
    if not ok:
        return why
    try:
        pp = Preprocessor.from_dict(mv.preprocessor)
    except (PreprocessingError, ValueError, KeyError) as exc:
        raise Conflict(f"cannot explain: the stored preprocessing can't be rebuilt ({exc})") from exc
    return model, pp


def _explain_verified(mv: ModelVersion, model: Any, pp: Preprocessor, preds: list[Prediction],
                      events: list[Event]) -> list[Any]:
    """Re-score the events, require every stored prediction to be reproduced, then explain them."""
    for pred in preds:
        if pp.version_id != pred.preprocessing_version:
            raise Conflict(f"cannot explain: the prediction used preprocessing {pred.preprocessing_version}, "
                           f"but the model now rebuilds {pp.version_id}")
    feats = pp.schema.feature_names
    frame = pd.DataFrame([{f: (np.nan if e.features.get(f) is None else e.features.get(f)) for f in feats}
                          for e in events]).astype("float64")
    try:
        predictor = Predictor(model, mv.version_id, pp, positive_class=mv.positive_class, threshold=mv.threshold)
        again = predictor.predict(frame, event_ids=[e.id for e in events])
        X = predictor.model_frame(frame)
    except (InferenceError, PreprocessingError) as exc:
        raise Conflict(f"cannot explain: re-scoring the event failed ({exc})") from exc
    for pred, (_, row) in zip(preds, again.iterrows()):
        same_score = (pred.score is None and pd.isna(row["score"])) or (
            pred.score is not None and not pd.isna(row["score"])
            and abs(float(row["score"]) - pred.score) <= SCORE_TOLERANCE)
        if row["status"] != "ok" or str(row["predicted_class"]) != pred.predicted_class or not same_score:
            raise Conflict("cannot explain: the model no longer reproduces this stored prediction, so an "
                           "explanation computed now would not describe it")
    if len(X) != len(preds):
        raise Conflict("cannot explain: preprocessing rejected an event that was scored")
    # The shown score is the probability of this class: the positive class under a threshold rule,
    # otherwise the predicted class (the score is its maximum class probability).
    use_positive = mv.threshold is not None and mv.positive_class is not None
    targets = [mv.positive_class if use_positive else p.predicted_class for p in preds]
    try:
        return explain_rows(model, X, targets)
    except ExplanationError as exc:
        raise Conflict(f"cannot explain: {exc}") from exc


def for_prediction(db: Session, prediction_id: int, cache: ModelCache) -> dict[str, Any]:
    pred = db.get(Prediction, prediction_id)
    if pred is None:
        raise NotFound(f"prediction {prediction_id} not found")
    event = db.get(Event, pred.event_id)
    mv = db.get(ModelVersion, pred.model_version_id)
    stored = db.scalar(select(PredictionExplanation).where(PredictionExplanation.prediction_id == pred.id))
    if stored is not None and stored.artifact_sha256 == mv.artifact_sha256:
        return _out(stored, event)
    if pred.status != "ok" or pred.predicted_class is None:
        return _unavailable("This event was rejected during scoring, so there is no prediction to explain.")
    loaded = _model_and_preprocessing(mv, cache)
    if isinstance(loaded, str):
        return _unavailable(loaded)
    exp = _explain_verified(mv, *loaded, [pred], [event])[0]

    row = stored or PredictionExplanation(prediction_id=pred.id)
    row.model_version_id = mv.id
    row.artifact_sha256 = mv.artifact_sha256
    row.preprocessing_version = pred.preprocessing_version
    row.method, row.library, row.output_space = exp.method, exp.library, exp.output_space
    row.target_class, row.base_value, row.model_output = exp.target_class, exp.base_value, exp.model_output
    row.additivity_error = exp.additivity_error
    row.contributions = [{"feature": c.feature, "model_input": c.model_input, "contribution": c.contribution}
                         for c in exp.contributions]
    row.limitations = exp.limitations
    if stored is None:
        db.add(row)
    db.flush()
    return _out(row, event)


SUMMARY_TOP = 10


def summarize(db: Session, cache: ModelCache, import_id: int, model_version_id: int, *,
              sample_per_group: int = 200, seed: int = 0) -> dict[str, Any]:
    """Mean absolute SHAP contribution per feature, for a seeded sample of a scoring run's predictions.

    With dataset labels, predictions are grouped by how they relate to the file's label (alert on an
    attack label, alert on a benign label, attack label without an alert), so the summary can show what
    drives detections, false positives and misses. Without labels there is one group: alerts.
    """
    mv = db.get(ModelVersion, model_version_id)
    if mv is None:
        raise NotFound(f"model version {model_version_id} not found")
    rows = list(db.execute(select(Prediction, Event).join(Event, Prediction.event_id == Event.id)
                           .where(Event.import_id == import_id, Prediction.model_version_id == mv.id,
                                  Prediction.status == "ok").order_by(Prediction.id)))
    if not rows:
        raise NotFound(f"no scored predictions for import {import_id} and model {model_version_id}")
    labelled = all(e.dataset_label is not None for _, e in rows)
    groups: dict[str, list[tuple[Prediction, Event]]] = {}
    for p, e in rows:
        if not labelled:
            key = "alerts" if p.is_suspicious else None
        elif p.is_suspicious:
            key = "alert_benign_label" if e.dataset_label == mv.benign_label else "alert_attack_label"
        else:
            key = "missed_attack_label" if e.dataset_label != mv.benign_label else None
        if key:
            groups.setdefault(key, []).append((p, e))
    loaded = _model_and_preprocessing(mv, cache)
    if isinstance(loaded, str):
        raise Conflict(f"cannot explain: {loaded}")
    rng = random.Random(seed)  # seeded for a reproducible sample, not for security  # nosec B311
    out_groups: dict[str, Any] = {}
    meta: dict[str, Any] = {}
    for key in ("alert_attack_label", "alert_benign_label", "missed_attack_label", "alerts"):
        members = groups.get(key)
        if not members:
            continue
        chosen = sorted(rng.sample(range(len(members)), min(sample_per_group, len(members))))
        sample = [members[i] for i in chosen]
        exps = _explain_verified(mv, *loaded, [p for p, _ in sample], [e for _, e in sample])
        feats = [c.feature for c in exps[0].contributions]
        mat = np.array([[{c.feature: c.contribution for c in x.contributions}[f] for f in feats] for x in exps])
        mean_abs = np.abs(mat).mean(axis=0)
        order = np.argsort(-mean_abs, kind="stable")[:SUMMARY_TOP]
        targets: dict[str, int] = {}
        for x in exps:
            targets[x.target_class] = targets.get(x.target_class, 0) + 1
        out_groups[key] = {
            "predictions": len(members), "sampled": len(sample), "explained_classes": targets,
            "max_additivity_error": max(x.additivity_error for x in exps),
            "top_features": [{"feature": feats[i], "mean_abs_contribution": float(mean_abs[i]),
                              "mean_contribution": float(mat[:, i].mean())} for i in order],
        }
        meta = {"method": exps[0].method, "library": exps[0].library, "output_space": exps[0].output_space}
    return {
        "model_version": mv.version_id, "artifact_sha256": mv.artifact_sha256, "import_id": import_id,
        "labelled": labelled, "benign_label": mv.benign_label, "seed": seed, "sample_per_group": sample_per_group,
        **meta, "groups": out_groups,
        "basis": ("dataset-provided labels from the imported file; not analyst-confirmed outcomes"
                  if labelled else "alerts only; the import has no labels"),
    }
