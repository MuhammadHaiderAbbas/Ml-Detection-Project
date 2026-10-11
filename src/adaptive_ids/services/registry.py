"""Model versions: registration from experiment runs and a manual, audited lifecycle.

Lifecycle: candidate -> approved -> active -> archived, or candidate -> rejected.
Promotion is always an explicit admin action with a recorded reason; nothing in
the system promotes a model automatically (not even a drift signal).
Rollback = activating an archived version that was previously approved.

Approval needs a completed evaluation of the candidate under the *current*
protocol and against the *current* baseline (see ``services.governance``):
``pass`` approves; ``fail`` approves only with an explicit, justified override
(audited as ``model.approve_override``); ``insufficient_evidence`` never does.
Approval and every activation or rollback first prove the artifact can be
restored (hash, trusted load, preprocessing, replay of a recorded sample).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import ModelEvaluation, ModelStatusChange, ModelVersion, User, utcnow
from ..preprocessing import PreprocessingError, Preprocessor
from ..provenance import sha256_file
from ..schema import FeatureSchema, SchemaError
from ..settings import Settings
from . import audit
from .errors import Conflict, InvalidRequest, NotFound

STATUSES = ("candidate", "evaluating", "approved", "active", "archived", "rejected")
_RUN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")


def _change(db: Session, mv: ModelVersion, to: str, actor: User | None, reason: str | None) -> None:
    db.add(ModelStatusChange(model_version_id=mv.id, from_status=mv.status, to_status=to,
                             changed_by_id=actor.id if actor else None, reason=reason))
    mv.status = to


def register_from_run(db: Session, run_name: str, settings: Settings, actor: User, client_ip: str | None = None) -> ModelVersion:
    """Register the model evaluated by an experiment run as a *candidate*."""
    if not _RUN_RE.match(run_name):
        raise InvalidRequest("invalid run name")
    base = Path(settings.runs_dir).resolve()
    run_dir = (base / run_name).resolve()
    if base not in run_dir.parents or not run_dir.is_dir():
        raise NotFound("experiment run not found")
    try:
        result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
        pp_dict = json.loads((run_dir / "preprocessor.json").read_text(encoding="utf-8"))
        pp = Preprocessor.from_dict(pp_dict)
    except (OSError, ValueError, KeyError, PreprocessingError, SchemaError) as exc:
        raise InvalidRequest(f"run is incomplete or invalid: {exc}") from exc
    model = result["model"]
    version_id = model["model_version"]
    if db.scalar(select(ModelVersion).where(ModelVersion.version_id == version_id)):
        raise Conflict(f"model version {version_id} is already registered")
    artifact = Path(model["resolved_path"])
    if not artifact.is_file() or sha256_file(artifact) != model["sha256"]:
        raise InvalidRequest("model artifact is missing or does not match the hash recorded by the run")
    cfg = result.get("config", {})
    test = (result.get("metrics") or {}).get("test")
    benign = None
    if test and test.get("binary_attack_vs_benign"):
        benign = test["binary_attack_vs_benign"]["benign_label"]
    benign = benign or cfg.get("evaluation", {}).get("benign_label") or pp.schema.benign_label
    decision = cfg.get("decision", {})
    if benign is None and decision.get("positive_class") is None:
        raise InvalidRequest("cannot decide which predictions are suspicious: no benign label or positive class")
    mv = ModelVersion(
        version_id=version_id,
        name=model.get("model_name") or model["artifact_id"],
        model_type=model.get("model_type") or model.get("estimator_class", ""),
        artifact_path=str(artifact),
        artifact_sha256=model["sha256"],
        artifact_format=model.get("format", "joblib"),
        provenance=result["provenance"],
        feature_schema=pp.schema.to_dict(),
        feature_schema_id=pp.schema.schema_id,
        preprocessor=pp_dict,
        preprocessing_version=pp.version_id,
        positive_class=None if decision.get("positive_class") is None else str(decision["positive_class"]),
        threshold=decision.get("threshold"),
        benign_label=benign,
        training_dataset=model.get("training_dataset") or None,
        training_config={"model": cfg.get("model"), "split": result.get("split"), "preprocessing": cfg.get("preprocessing")},
        software_versions=(result.get("environment") or {}).get("packages", {}),
        evaluation={
            "experiment_id": result["experiment_id"],
            "provenance": result["provenance"],
            "result_sha256": result.get("result_sha256"),
            "dataset": {k: result["dataset"].get(k) for k in ("name", "version", "file_sha256", "accepted_rows")},
            "split_method": (result.get("split") or {}).get("method"),
            "test": test,
            "limitations": result.get("limitations", []),
        },
        source_run=run_name,
        status="candidate",
        registered_by_id=actor.id,
    )
    db.add(mv)
    db.flush()
    db.add(ModelStatusChange(model_version_id=mv.id, from_status=None, to_status="candidate",
                             changed_by_id=actor.id, reason=f"registered from run {run_name}"))
    audit.record(db, "model.register", actor=actor, entity_type="model_version", entity_id=mv.id,
                 details={"version_id": version_id, "run": run_name, "provenance": mv.provenance}, client_ip=client_ip)
    return mv


def get(db: Session, model_id: int) -> ModelVersion:
    mv = db.get(ModelVersion, model_id)
    if mv is None:
        raise NotFound("model version not found")
    return mv


def get_active(db: Session) -> ModelVersion | None:
    return db.scalar(select(ModelVersion).where(ModelVersion.status == "active"))


def _need_reason(reason: str | None) -> str:
    if not reason or not reason.strip():
        raise InvalidRequest("a reason is required for this action")
    return reason.strip()


MIN_OVERRIDE_JUSTIFICATION = 20


def approve(db: Session, model_id: int, actor: User, reason: str | None, settings: Settings, *,
            evaluation_id: int | None = None, override: bool = False, client_ip: str | None = None) -> ModelVersion:
    from . import governance

    mv = get(db, model_id)
    reason = _need_reason(reason)
    if mv.status not in ("candidate", "evaluating"):
        raise Conflict(f"only candidate models can be approved (status is {mv.status})")
    if not (mv.evaluation or {}).get("test"):
        raise InvalidRequest("a model cannot be approved without recorded test-set evaluation results")
    if evaluation_id is not None:
        ev = governance.get_evaluation(db, evaluation_id)
        if ev.model_version_id != mv.id:
            raise InvalidRequest("that evaluation belongs to another model version")
    else:
        ev = db.scalar(select(ModelEvaluation).where(ModelEvaluation.model_version_id == mv.id,
                                                     ModelEvaluation.status == "completed")
                       .order_by(ModelEvaluation.completed_at.desc(), ModelEvaluation.id.desc()))
    if ev is None or ev.status != "completed":
        raise Conflict("approval requires a completed candidate evaluation; evaluate the model on labelled data first")
    proto = governance.current_protocol(settings)
    if ev.protocol != proto.to_dict():
        raise Conflict(f"evaluation {ev.id} used protocol v{ev.protocol_version}; the current protocol is "
                       f"v{proto.version}. Re-evaluate the candidate")
    active = get_active(db)
    if (active.id if active else None) != ev.baseline_model_version_id:
        raise Conflict(f"the active model changed after evaluation {ev.id}; re-evaluate against the current baseline")
    failed = [g["id"] for g in ev.gates or [] if g["passed"] is False]
    if ev.verdict == "insufficient_evidence":
        raise Conflict(f"evaluation {ev.id} did not have enough valid evidence ({', '.join(failed)}); "
                       "this cannot be overridden")
    if ev.verdict == "fail":
        if not override:
            raise Conflict(f"evaluation {ev.id} failed {', '.join(failed)}; approving needs an explicit override "
                           "with a written justification")
        if len(reason) < MIN_OVERRIDE_JUSTIFICATION:
            raise InvalidRequest(f"an override needs a justification of at least {MIN_OVERRIDE_JUSTIFICATION} characters")
    elif ev.verdict != "pass":
        raise Conflict(f"evaluation {ev.id} has no usable verdict")
    elif override:
        raise InvalidRequest("override is only for evaluations that failed a performance gate")
    check = governance.verify_restorable(mv, ev.reference_sample)
    mv.restore_check = check
    if not check["ok"]:
        raise Conflict("the artifact could not be restored and replayed: "
                       + "; ".join(c["detail"] for c in check["checks"] if c["passed"] is False))
    _change(db, mv, "approved", actor, f"[override of failed gates: {', '.join(failed)}] {reason}" if override else reason)
    mv.approved_by_id, mv.approved_at = actor.id, utcnow()
    mv.approval_evaluation_id, mv.approval_override = ev.id, bool(override)
    mv.reference_sample = ev.reference_sample
    audit.record(db, "model.approve_override" if override else "model.approve", actor=actor,
                 entity_type="model_version", entity_id=mv.id,
                 details={"version_id": mv.version_id, "reason": reason, "evaluation_id": ev.id,
                          "verdict": ev.verdict, "failed_gates": failed, "protocol": ev.protocol_version},
                 client_ip=client_ip)
    return mv


def reject(db: Session, model_id: int, actor: User, reason: str | None, client_ip: str | None = None) -> ModelVersion:
    mv = get(db, model_id)
    reason = _need_reason(reason)
    if mv.status not in ("candidate", "evaluating"):
        raise Conflict(f"only candidate models can be rejected (status is {mv.status})")
    _change(db, mv, "rejected", actor, reason)
    audit.record(db, "model.reject", actor=actor, entity_type="model_version", entity_id=mv.id,
                 details={"version_id": mv.version_id, "reason": reason}, client_ip=client_ip)
    return mv


def activate(db: Session, model_id: int, actor: User, reason: str | None, client_ip: str | None = None) -> ModelVersion:
    """Make an approved (or previously approved, archived) version the active one."""
    mv = get(db, model_id)
    reason = _need_reason(reason)
    if mv.status == "active":
        raise Conflict("model is already active")
    if mv.status not in ("approved", "archived") or mv.approved_at is None:
        raise Conflict("only approved models (or archived models that were approved) can be activated")
    from . import governance

    check = governance.verify_restorable(mv)
    mv.restore_check = check
    if not check["ok"]:
        raise Conflict(f"{mv.version_id} cannot be restored, so it was not activated: "
                       + "; ".join(c["detail"] for c in check["checks"] if c["passed"] is False))
    current = get_active(db)
    if current is not None:
        _change(db, current, "archived", actor, f"replaced by {mv.version_id}: {reason}")
    rollback = mv.status == "archived"
    _change(db, mv, "active", actor, reason)
    mv.activated_at = utcnow()
    audit.record(db, "model.rollback" if rollback else "model.activate", actor=actor, entity_type="model_version",
                 entity_id=mv.id, details={"version_id": mv.version_id, "reason": reason,
                                           "previous_active": current.version_id if current else None,
                                           "restore_check": {"ok": check["ok"], "partial": check["partial"]}},
                 client_ip=client_ip)
    return mv


def history(db: Session, model_id: int) -> list[ModelStatusChange]:
    get(db, model_id)
    return list(db.scalars(select(ModelStatusChange).where(ModelStatusChange.model_version_id == model_id)
                           .order_by(ModelStatusChange.changed_at, ModelStatusChange.id)))


def schema_of(mv: ModelVersion) -> FeatureSchema:
    return FeatureSchema.from_dict(mv.feature_schema)


def summary(mv: ModelVersion) -> dict[str, Any]:
    return {"id": mv.id, "version_id": mv.version_id, "name": mv.name, "status": mv.status,
            "provenance": mv.provenance}
