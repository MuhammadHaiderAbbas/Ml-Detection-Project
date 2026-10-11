"""Repeatable SYNTHETIC demonstration: train -> register -> evaluate -> approve -> activate -> import -> score
-> drift analysis -> a second candidate evaluated against the active model and left for a human decision.

Everything created here is labelled ``synthetic_demo``. It exists to show the
software working end to end, not to say anything about detection performance.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from .db import make_engine, make_session_factory, session_scope
from .db.models import User
from .experiments import run_experiment
from .research import write_synthetic_dataset
from .services import governance, imports, registry, scoring
from .services.severity import SeverityRules
from .settings import Settings

TRAIN_FILE = Path("data/sample/flows_SYNTHETIC_demo.csv")
BASELINE_FILE = Path("data/sample/flows_SYNTHETIC_baseline.csv")
REPLAY_FILE = Path("data/sample/flows_SYNTHETIC_replay.csv")
CONFIG = Path("configs/experiments/synthetic-demo.json")
CANDIDATE_CONFIG = Path("configs/experiments/synthetic-demo-candidate.json")
STEPS = 8


def _train(config: Path, settings: Settings) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = json.loads(config.read_text(encoding="utf-8"))
        cfg["output_dir"] = str(settings.runs_dir)
        cfg_path = Path(tmp) / "demo.json"
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        return Path(run_experiment(cfg_path)["run_dir"]).name


def run_demo(settings: Settings, *, admin_username: str, log=print) -> dict:
    factory = make_session_factory(make_engine(settings.database_url))
    with session_scope(factory) as db:
        admin = db.scalar(select(User).where(User.username == admin_username))
        if admin is None or admin.role != "admin":
            raise SystemExit(f"error: '{admin_username}' is not an existing admin user")
        admin_id = admin.id

    log(f"1/{STEPS} Generating SYNTHETIC training data and running the demo experiment ...")
    write_synthetic_dataset(TRAIN_FILE, n_rows=5000, seed=7)
    run_name = _train(CONFIG, settings)

    log(f"2/{STEPS} Generating SYNTHETIC replay data: a stable baseline week and a later week where benign traffic shifts ...")
    write_synthetic_dataset(BASELINE_FILE, n_rows=3000, seed=10)
    write_synthetic_dataset(REPLAY_FILE, n_rows=3000, seed=11, drift_after_fraction=0.5, drift_strength=0.8,
                            start=datetime(2026, 1, 12, 9, 0, tzinfo=timezone.utc))
    schema = imports.get_schema(settings, "synthetic-flows-demo@1.1.0")
    stored = Path(settings.storage_dir) / "uploads"
    stored.mkdir(parents=True, exist_ok=True)
    import_ids = []
    for src, name, version in ((BASELINE_FILE, "synthetic-baseline", "seed10-n3000"),
                               (REPLAY_FILE, "synthetic-replay", "seed11-n3000-drift0.5")):
        dest = stored / f"demo-{name}-{run_name}.csv"
        shutil.copyfile(src, dest)
        with session_scope(factory) as db:
            rec = imports.create_import(
                db, stored_path=dest, original_filename=src.name, schema=schema, dataset_name=name,
                dataset_version=version, provenance="synthetic_demo", data_source="demo replay (SYNTHETIC)",
                column_mapping={}, duplicate_policy="keep", actor=db.get(User, admin_id))
            import_id = rec.id
        imports.run_import(factory, import_id, settings, imports.CancelRegistry())
        import_ids.append(import_id)

    cache = scoring.ModelCache()
    log(f"3/{STEPS} Registering the demo model, evaluating it on the baseline week, then approving and activating it "
        "(explicit admin actions) ...")
    with session_scope(factory) as db:
        mv = registry.register_from_run(db, run_name, settings, db.get(User, admin_id))
        model_id = mv.id
        ev = governance.start_evaluation(db, model_id, import_ids[0], settings, db.get(User, admin_id))
        first_eval = ev.id
    governance.run_evaluation(factory, first_eval, cache)
    with session_scope(factory) as db:
        admin = db.get(User, admin_id)
        registry.approve(db, model_id, admin, "Demo: SYNTHETIC model approved after passing protocol v1 (no baseline yet)",
                         settings, evaluation_id=first_eval)
        registry.activate(db, model_id, admin, "Demo activation (SYNTHETIC)")

    rules = SeverityRules.load(settings.severity_rules_path)
    for step, import_id in enumerate(import_ids):
        log(f"{4 + step}/{STEPS} Scoring import {import_id} with the active model ...")
        with session_scope(factory) as db:
            run = scoring.start_scoring(db, import_id, None, settings, db.get(User, admin_id))
            run_id = run.id
        scoring.run_scoring(factory, run_id, rules, cache)

    log(f"6/{STEPS} Running a drift analysis: baseline (reference) vs replay (current) ...")
    from .services import drift as drift_svc

    with session_scope(factory) as db:
        a = drift_svc.start_analysis(db, {"name": "Demo: baseline week vs replay week (SYNTHETIC)",
                                          "reference": {"import_id": import_ids[0]}, "current": {"import_id": import_ids[1]},
                                          "window": {"mode": "events", "size": 250}}, settings, db.get(User, admin_id))
        analysis_id = a.id
    drift_svc.run_analysis(factory, analysis_id)

    log(f"7/{STEPS} Training a second SYNTHETIC candidate (shallow decision tree) and registering it ...")
    cand_run = _train(CANDIDATE_CONFIG, settings)
    with session_scope(factory) as db:
        cand = registry.register_from_run(db, cand_run, settings, db.get(User, admin_id))
        candidate_id = cand.id
        ev = governance.start_evaluation(db, candidate_id, import_ids[1], settings, db.get(User, admin_id))
        cand_eval = ev.id
    log(f"8/{STEPS} Evaluating the candidate against the active model on the replay week; "
        "it stays a candidate until an admin decides ...")
    governance.run_evaluation(factory, cand_eval, cache)
    with session_scope(factory) as db:
        from .db.models import ModelEvaluation

        verdict = db.get(ModelEvaluation, cand_eval).verdict
    summary = {"experiment_run": run_name, "model_version_id": model_id, "import_ids": import_ids,
               "drift_analysis_id": analysis_id, "candidate_model_id": candidate_id,
               "evaluations": {"active_model": first_eval, "candidate": cand_eval}, "candidate_verdict": verdict}
    log(f"Done (SYNTHETIC demo): {summary}")
    return summary
