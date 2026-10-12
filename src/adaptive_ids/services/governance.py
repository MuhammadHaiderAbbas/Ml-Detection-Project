"""Model governance: candidate evaluation under a versioned protocol, and restorability checks.

An evaluation scores a candidate and the baseline (the model active when the
evaluation starts) on the same labelled import and applies the protocol's gates
(see :mod:`adaptive_ids.governance.protocol`). Approval in the registry requires
a passing evaluation, or an audited override of a valid but failing one.

A restorability check proves a registered artifact can still be brought back:
the file exists, its hash matches the registry, it loads through the trusted
loader, its preprocessing state is intact, and it reproduces the outputs it gave
on a recorded input sample when it was approved. Activation and rollback run it
first and refuse when it fails.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from ..db.models import DatasetImport, Event, ModelEvaluation, ModelVersion, User, utcnow
from ..db.session import session_scope
from ..detection import ArtifactTrustError, InferenceError, Predictor, load_verified_artifact
from ..governance import EvaluationProtocol, ProtocolError, compare_models, load_protocol
from ..preprocessing import PreprocessingError, Preprocessor
from ..provenance import sha256_file
from ..settings import Settings
from . import audit
from .errors import Conflict, InvalidRequest, NotFound
from .scoring import ModelCache, is_suspicious

log = logging.getLogger(__name__)
MAX_EVALUATION_EVENTS = 1_000_000
BATCH = 20_000
SCORE_TOLERANCE = 1e-9


def current_protocol(settings: Settings) -> EvaluationProtocol:
    try:
        return load_protocol(settings.evaluation_protocol_path)
    except ProtocolError as exc:
        raise InvalidRequest(str(exc)) from exc


def _feature_names(mv: ModelVersion) -> list[str]:
    return [f["name"] for f in mv.feature_schema["features"]]


def _training_hash(mv: ModelVersion) -> str | None:
    return ((mv.evaluation or {}).get("dataset") or {}).get("file_sha256")


def start_evaluation(db: Session, model_id: int, import_id: int, settings: Settings, actor: User,
                     client_ip: str | None = None) -> ModelEvaluation:
    mv = db.get(ModelVersion, model_id)
    if mv is None:
        raise NotFound("model version not found")
    if mv.status not in ("candidate", "evaluating"):
        raise Conflict(f"only candidate models are evaluated for approval (status is {mv.status})")
    imp = db.get(DatasetImport, import_id)
    if imp is None:
        raise NotFound("import not found")
    if imp.status != "completed":
        raise Conflict(f"only completed imports can be used (status is {imp.status})")
    from .imports import get_schema

    data_feats = set(get_schema(settings, imp.schema_id).feature_names)
    if not set(_feature_names(mv)) <= data_feats:
        raise InvalidRequest(f"import schema {imp.schema_id} does not provide the features {mv.version_id} needs")
    baseline = db.scalar(select(ModelVersion).where(ModelVersion.status == "active"))
    for who, m in (("candidate", mv), ("baseline", baseline)):
        if m is not None and imp.file_sha256 and _training_hash(m) == imp.file_sha256:
            raise InvalidRequest(
                f"import {imp.id} is the file the {who} ({m.version_id}) was trained and tested from; "
                "evaluate on data neither model has seen")
    if baseline is not None and not set(_feature_names(baseline)) <= data_feats:
        raise InvalidRequest(
            f"the active model {baseline.version_id} cannot score this import, so the comparison would not be like for like")
    n_labelled = db.scalar(select(func.count()).select_from(Event).where(
        Event.import_id == imp.id, Event.dataset_label.is_not(None))) or 0
    if n_labelled > MAX_EVALUATION_EVENTS:
        raise InvalidRequest(f"import has {n_labelled} labelled events; the limit per evaluation is {MAX_EVALUATION_EVENTS}")
    busy = db.scalar(select(ModelEvaluation).where(ModelEvaluation.model_version_id == mv.id,
                                                   ModelEvaluation.status.in_(("queued", "running"))))
    if busy:
        raise Conflict(f"evaluation {busy.id} of this model is still running")
    proto = current_protocol(settings)
    ev = ModelEvaluation(
        model_version_id=mv.id, baseline_model_version_id=baseline.id if baseline else None, import_id=imp.id,
        protocol=proto.to_dict(), protocol_version=proto.version, status="queued", created_by_id=actor.id,
        data={"import_id": imp.id, "dataset": f"{imp.dataset_name}@{imp.dataset_version}", "provenance": imp.provenance,
              "file_sha256": imp.file_sha256, "schema_id": imp.schema_id, "labelled_events": n_labelled,
              "candidate": {"version_id": mv.version_id, "provenance": mv.provenance,
                            "training_file_sha256": _training_hash(mv)},
              "baseline": None if baseline is None else {
                  "version_id": baseline.version_id, "provenance": baseline.provenance,
                  "training_file_sha256": _training_hash(baseline)},
              "truth": f"dataset label != {mv.benign_label!r} counts as attack (labels from the imported file)"},
    )
    db.add(ev)
    db.flush()
    audit.record(db, "model.evaluation_start", actor=actor, entity_type="model_evaluation", entity_id=ev.id,
                 details={"model": mv.version_id, "baseline": baseline.version_id if baseline else None,
                          "import_id": imp.id, "protocol": proto.version}, client_ip=client_ip)
    return ev


def _predict_all(mv: ModelVersion, model: Any, frame: pd.DataFrame, event_ids: list[int]) -> pd.DataFrame:
    pp = Preprocessor.from_dict(mv.preprocessor)
    predictor = Predictor(model, mv.version_id, pp, positive_class=mv.positive_class, threshold=mv.threshold)
    frame = frame[_feature_names(mv)]
    parts = [predictor.predict(frame.iloc[i:i + BATCH], event_ids=event_ids[i:i + BATCH])
             for i in range(0, len(frame), BATCH)]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def _flags(mv: ModelVersion, out: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    ok = (out["status"] == "ok").to_numpy()
    flag = np.array([is_suspicious(mv, c, s) for c, s in zip(out["predicted_class"], out["status"])], dtype=bool)
    return flag, ok


def run_evaluation(factory: sessionmaker[Session], evaluation_id: int, cache: ModelCache) -> None:
    t0 = time.perf_counter()
    with session_scope(factory) as db:
        ev = db.get(ModelEvaluation, evaluation_id)
        if ev is None or ev.status != "queued":
            return
        ev.status, ev.started_at = "running", utcnow()
    try:
        with session_scope(factory) as db:
            ev = db.get(ModelEvaluation, evaluation_id)
            cand = db.get(ModelVersion, ev.model_version_id)
            base = db.get(ModelVersion, ev.baseline_model_version_id) if ev.baseline_model_version_id else None
            proto = EvaluationProtocol.from_dict(ev.protocol)
            rows = db.execute(select(Event.id, Event.features, Event.dataset_label)
                              .where(Event.import_id == ev.import_id, Event.dataset_label.is_not(None))
                              .order_by(Event.id)).all()
            ids = [r.id for r in rows]
            names = sorted(set(_feature_names(cand)) | set(_feature_names(base) if base else []))
            frame = pd.DataFrame([{f: (np.nan if r.features.get(f) is None else r.features.get(f)) for f in names}
                                  for r in rows], columns=names).astype("float64")
            truth = np.array([str(r.dataset_label) != cand.benign_label for r in rows], dtype=bool)
            c_out = _predict_all(cand, cache.get(cand), frame, ids)
            c_flag, c_ok = _flags(cand, c_out) if len(rows) else (np.zeros(0, bool), np.zeros(0, bool))
            b_flag = b_ok = None
            if base is not None:
                b_out = _predict_all(base, cache.get(base), frame, ids)
                b_flag, b_ok = _flags(base, b_out) if len(rows) else (np.zeros(0, bool), np.zeros(0, bool))
            result = compare_models(truth, c_flag, c_ok, proto, b_flag, b_ok)
            ev.verdict, ev.gates = result.verdict, result.gates
            ev.results = {**result.to_dict(), "baseline_present": base is not None,
                          "basis": "dataset-provided labels from the imported file; not analyst-confirmed outcomes"}
            ev.reference_sample = _reference_sample(cand, frame, c_out, proto.reference_sample_size)
            ev.status, ev.completed_at = "completed", utcnow()
            ev.duration_ms = (time.perf_counter() - t0) * 1000
    except (ArtifactTrustError, InferenceError, PreprocessingError) as exc:
        _fail(factory, evaluation_id, str(exc), t0)
    except Exception:
        log.exception("evaluation %s failed", evaluation_id)
        _fail(factory, evaluation_id, "internal error during evaluation (see server log)", t0)


def _reference_sample(mv: ModelVersion, frame: pd.DataFrame, out: pd.DataFrame, size: int) -> dict[str, Any] | None:
    ok_idx = np.flatnonzero((out["status"] == "ok").to_numpy())[:size] if len(out) else []
    if not len(ok_idx):
        return None
    feats = _feature_names(mv)
    sub = frame.iloc[ok_idx][feats]
    return {
        "features": feats,
        "rows": [[None if pd.isna(v) else float(v) for v in row] for row in sub.itertuples(index=False)],
        "expected_class": [str(out["predicted_class"].iloc[i]) for i in ok_idx],
        "expected_score": [None if pd.isna(out["score"].iloc[i]) else float(out["score"].iloc[i]) for i in ok_idx],
    }


def _fail(factory: sessionmaker[Session], evaluation_id: int, message: str, t0: float) -> None:
    with session_scope(factory) as db:
        ev = db.get(ModelEvaluation, evaluation_id)
        if ev:
            ev.status, ev.error, ev.completed_at = "failed", message, utcnow()
            ev.duration_ms = (time.perf_counter() - t0) * 1000


def get_evaluation(db: Session, evaluation_id: int) -> ModelEvaluation:
    ev = db.get(ModelEvaluation, evaluation_id)
    if ev is None:
        raise NotFound("evaluation not found")
    return ev


def list_evaluations(db: Session, model_id: int | None = None) -> list[ModelEvaluation]:
    q = select(ModelEvaluation).order_by(ModelEvaluation.created_at.desc(), ModelEvaluation.id.desc())
    if model_id is not None:
        q = q.where(ModelEvaluation.model_version_id == model_id)
    return list(db.scalars(q))


# --------------------------------------------------------------------------- restorability


def verify_restorable(mv: ModelVersion, sample: dict[str, Any] | None = None) -> dict[str, Any]:
    """Re-load the artifact from disk (no cache) and replay the recorded sample."""
    sample = sample if sample is not None else mv.reference_sample
    checks: list[dict[str, Any]] = []

    def add(cid: str, ok: bool | None, detail: str) -> bool:
        checks.append({"id": cid, "passed": ok, "detail": detail})
        return bool(ok)

    model = pp = None
    path = Path(mv.artifact_path)
    if add("artifact_present", path.is_file(), str(path.name) if path.is_file() else f"missing: {path.name}"):
        actual = sha256_file(path)
        if add("artifact_hash", actual == mv.artifact_sha256,
               "matches the registry" if actual == mv.artifact_sha256 else f"file hash {actual[:16]}... differs"):
            try:
                model, warns = load_verified_artifact(path, mv.artifact_sha256, mv.artifact_format, label=mv.version_id)
                add("artifact_loads", True, "; ".join(warns) if warns else "loaded through the trusted loader")
            except ArtifactTrustError as exc:
                add("artifact_loads", False, str(exc))
    try:
        pp = Preprocessor.from_dict(mv.preprocessor)
        add("preprocessing_intact", pp.version_id == mv.preprocessing_version,
            f"version {pp.version_id}" if pp.version_id == mv.preprocessing_version
            else f"stored state hashes to {pp.version_id}, registry says {mv.preprocessing_version}")
    except (PreprocessingError, ValueError, KeyError) as exc:
        add("preprocessing_intact", False, f"cannot rebuild preprocessing: {exc}")
    mismatches = None
    if not sample:
        add("reference_outputs", None, "no recorded sample for this version (it was approved before samples were kept)")
    elif model is not None and pp is not None:
        try:
            frame = pd.DataFrame(sample["rows"], columns=sample["features"]).astype("float64")
            predictor = Predictor(model, mv.version_id, pp, positive_class=mv.positive_class, threshold=mv.threshold)
            out = predictor.predict(frame, event_ids=list(range(len(frame))))
            mismatches = 0
            for i, (cls, score) in enumerate(zip(out["predicted_class"], out["score"])):
                exp_s = sample["expected_score"][i]
                same_score = (exp_s is None and pd.isna(score)) or (
                    exp_s is not None and not pd.isna(score) and abs(float(score) - exp_s) <= SCORE_TOLERANCE)
                if str(cls) != sample["expected_class"][i] or not same_score:
                    mismatches += 1
            add("reference_outputs", mismatches == 0,
                f"{len(frame) - mismatches} of {len(frame)} recorded predictions reproduced exactly")
        except (InferenceError, PreprocessingError, KeyError, ValueError) as exc:
            add("reference_outputs", False, f"replay failed: {exc}")
    else:
        add("reference_outputs", False, "not attempted: the artifact or its preprocessing could not be restored")
    ok = all(c["passed"] is not False for c in checks)
    return {"ok": ok, "partial": any(c["passed"] is None for c in checks), "checked_at": utcnow().isoformat(),
            "checks": checks, "mismatches": mismatches, "sample_size": len(sample["rows"]) if sample else 0}


def record_restore_check(db: Session, mv: ModelVersion, actor: User, client_ip: str | None = None) -> dict[str, Any]:
    res = verify_restorable(mv)
    mv.restore_check = res
    audit.record(db, "model.restore_check", actor=actor, entity_type="model_version", entity_id=mv.id,
                 details={"version_id": mv.version_id, "ok": res["ok"], "partial": res["partial"]}, client_ip=client_ip)
    return res


# --------------------------------------------------------------------------- report


def _fmt(v: Any, pct: bool = True) -> str:
    if v is None:
        return "—"
    return f"{v * 100:.2f} %" if pct else f"{v:.4f}"


def _pp(v: Any) -> str:
    return "—" if v is None else f"{v * 100:+.2f} pp"


def _gate_value(gid: str, v: Any) -> str:
    if v is None:
        return "—"
    if gid.startswith("non_inferior_"):
        return _pp(v)
    if gid in ("labelled_events", "attack_events", "benign_events"):
        return f"{int(v):,}"
    return f"{v * 100:.2f} %"


def report_markdown(db: Session, ev: ModelEvaluation) -> str:
    cand = db.get(ModelVersion, ev.model_version_id)
    base = db.get(ModelVersion, ev.baseline_model_version_id) if ev.baseline_model_version_id else None
    d, r = ev.data or {}, ev.results or {}
    synthetic = "synthetic_demo" in {d.get("provenance"), cand.provenance, base.provenance if base else None}
    lines = [f"# Candidate evaluation #{ev.id}: {cand.version_id}", ""]
    if synthetic:
        lines += ["> **SYNTHETIC DEMO.** Synthetic data or a synthetic model is involved. These numbers show the "
                  "software working; they are not evidence about detection performance.", ""]
    lines += [
        f"- **Verdict:** {ev.verdict or ev.status}",
        f"- **Protocol:** v{ev.protocol_version} (`configs/evaluation-protocol.json`)",
        f"- **Candidate:** {cand.version_id} ({cand.provenance}, status {cand.status})",
        f"- **Baseline:** {base.version_id + ' (' + base.provenance + ')' if base else 'none (no active model when the evaluation started)'}",
        f"- **Data:** import #{d.get('import_id')} {d.get('dataset')} ({d.get('provenance')}), SHA-256 `{d.get('file_sha256')}`",
        f"- **Truth:** {d.get('truth')}. {r.get('basis', '')}",
        f"- **Run:** {ev.created_at.isoformat() if ev.created_at else ''}, {(ev.duration_ms or 0) / 1000:.1f} s",
        "",
    ]
    if ev.status != "completed":
        lines += [f"Evaluation {ev.status}. {ev.error or ''}", ""]
        return "\n".join(lines)
    m = r.get("metrics", {})
    names = [("attack_recall", "Attack recall (detection rate)"), ("false_positive_rate", "False-positive rate"),
             ("precision", "Precision"), ("f1", "F1"), ("accuracy", "Accuracy")]
    lines += ["## Metrics (attack vs benign)", ""]
    if base:
        conf = f"{float(ev.protocol.get('confidence', 0.95)):.0%}".replace("%", " %")
        lines += [f"| Metric | Candidate | Baseline | Difference | {conf} CI of difference |", "|---|---|---|---|---|"]
        for k, label in names:
            diff = r["differences"].get(k, {})
            lines.append(f"| {label} | {_fmt(m['candidate'][k])} | {_fmt(m['baseline'][k])} | "
                         f"{_pp(diff.get('difference'))} | [{_pp(diff.get('ci_low'))}, {_pp(diff.get('ci_high'))}] |")
    else:
        lines += ["| Metric | Candidate |", "|---|---|"]
        lines += [f"| {label} | {_fmt(m['candidate'][k])} |" for k, label in names]
    c = r.get("counts", {})
    lines += ["", f"Compared events: {c.get('compared_events', 0):,} ({c.get('attack_events', 0):,} attack, "
              f"{c.get('benign_events', 0):,} benign) of {c.get('labelled_events', 0):,} labelled. "
              "Differences are candidate - baseline in percentage points (pp).", ""]
    lines += ["## Gates", "", "| Gate | Kind | Result | Value | Threshold |", "|---|---|---|---|---|"]
    for g in ev.gates or []:
        res = "pass" if g["passed"] else ("fail" if g["passed"] is False else "n/a")
        lines.append(f"| {g['detail']} | {g['kind']} | {res} | {_gate_value(g['id'], g['value'])} | "
                     f"{_gate_value(g['id'], g['threshold'])} |")
    if r.get("mcnemar"):
        mc = r["mcnemar"]
        lines += ["", "## McNemar test (context only, not a gate)", "",
                  f"Candidate right where the baseline was wrong: {mc['candidate_only_correct']}; the reverse: "
                  f"{mc['baseline_only_correct']}. {mc['method']}, p = {mc['p_value']:.4g} "
                  f"({'significant' if mc.get('significant') else 'not significant'} at {mc.get('alpha')})."]
    lines += ["", "## Limitations", "",
              "- Labels come from the imported file. They are not analyst-confirmed outcomes.",
              "- Metrics treat every non-benign label as an attack; per-class behaviour is not gated.",
              "- The evaluation file is checked against each model's training file by hash only; "
              "overlapping rows inside a different file are not detected.",
              "- Scores are uncalibrated; the comparison uses each model's own decision rule.", ""]
    return "\n".join(lines)
