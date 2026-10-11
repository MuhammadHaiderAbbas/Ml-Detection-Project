"""Repeatable SYNTHETIC demonstration: train -> register -> approve -> activate -> import -> score.

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
from .services import imports, registry, scoring
from .services.severity import SeverityRules
from .settings import Settings

TRAIN_FILE = Path("data/sample/flows_SYNTHETIC_demo.csv")
BASELINE_FILE = Path("data/sample/flows_SYNTHETIC_baseline.csv")
REPLAY_FILE = Path("data/sample/flows_SYNTHETIC_replay.csv")
CONFIG = Path("configs/experiments/synthetic-demo.json")


def run_demo(settings: Settings, *, admin_username: str, log=print) -> dict:
    factory = make_session_factory(make_engine(settings.database_url))
    with session_scope(factory) as db:
        admin = db.scalar(select(User).where(User.username == admin_username))
        if admin is None or admin.role != "admin":
            raise SystemExit(f"error: '{admin_username}' is not an existing admin user")
        admin_id = admin.id

    log("1/6 Generating SYNTHETIC training data and running the demo experiment ...")
    write_synthetic_dataset(TRAIN_FILE, n_rows=5000, seed=7)
    with tempfile.TemporaryDirectory() as tmp:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        cfg["output_dir"] = str(settings.runs_dir)
        cfg_path = Path(tmp) / "demo.json"
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        result = run_experiment(cfg_path)
    run_name = Path(result["run_dir"]).name

    log("2/6 Registering, approving and activating the demo model (explicit admin actions) ...")
    with session_scope(factory) as db:
        admin = db.get(User, admin_id)
        mv = registry.register_from_run(db, run_name, settings, admin)
        registry.approve(db, mv.id, admin, "Demo: SYNTHETIC model approved to exercise the workflow only")
        registry.activate(db, mv.id, admin, "Demo activation (SYNTHETIC)")
        model_id = mv.id

    log("3/6 Generating SYNTHETIC replay data: a stable baseline week and a later week where benign traffic shifts ...")
    write_synthetic_dataset(BASELINE_FILE, n_rows=3000, seed=10)
    write_synthetic_dataset(REPLAY_FILE, n_rows=3000, seed=11, drift_after_fraction=0.5, drift_strength=0.8,
                            start=datetime(2026, 1, 12, 9, 0, tzinfo=timezone.utc))
    schema = imports.get_schema(settings, "synthetic-flows-demo@1.1.0")
    stored = Path(settings.storage_dir) / "uploads"
    stored.mkdir(parents=True, exist_ok=True)

    import_ids = []
    rules = SeverityRules.load(settings.severity_rules_path)
    cache = scoring.ModelCache()
    for step, (src, name, version) in enumerate(((BASELINE_FILE, "synthetic-baseline", "seed10-n3000"),
                                                (REPLAY_FILE, "synthetic-replay", "seed11-n3000-drift0.5"))):
        log(f"{4 + step}/6 Importing and scoring {src.name} ...")
        dest = stored / f"demo-{name}-{run_name}.csv"
        shutil.copyfile(src, dest)
        with session_scope(factory) as db:
            rec = imports.create_import(
                db, stored_path=dest, original_filename=src.name, schema=schema, dataset_name=name,
                dataset_version=version, provenance="synthetic_demo", data_source="demo replay (SYNTHETIC)",
                column_mapping={}, duplicate_policy="keep", actor=db.get(User, admin_id))
            import_id = rec.id
        imports.run_import(factory, import_id, settings, imports.CancelRegistry())
        with session_scope(factory) as db:
            run = scoring.start_scoring(db, import_id, None, settings, db.get(User, admin_id))
            run_id = run.id
        scoring.run_scoring(factory, run_id, rules, cache)
        import_ids.append(import_id)

    log("6/6 Running a drift analysis: baseline (reference) vs replay (current) ...")
    from .services import drift as drift_svc

    with session_scope(factory) as db:
        a = drift_svc.start_analysis(db, {"name": "Demo: baseline week vs replay week (SYNTHETIC)",
                                          "reference": {"import_id": import_ids[0]}, "current": {"import_id": import_ids[1]},
                                          "window": {"mode": "events", "size": 250}}, settings, db.get(User, admin_id))
        analysis_id = a.id
    drift_svc.run_analysis(factory, analysis_id)
    summary = {"experiment_run": run_name, "model_version_id": model_id, "import_ids": import_ids, "drift_analysis_id": analysis_id}
    log(f"Done (SYNTHETIC demo): {summary}")
    return summary
