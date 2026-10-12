"""Measure what a single-machine deployment needs: throughput, latency, memory and storage.

Runs the real application in-process (FastAPI test client, the configured services, a fresh
database) through the operator workflow:

  import a training-free CSV -> evaluate and approve the model -> activate -> import a replay
  -> score -> open alert explanations -> drift analysis -> backup

and records wall-clock time per step, events per second, process peak memory and database size.
Nothing is estimated: every number is measured on the machine this runs on, which is recorded.

Two modes:

* ``--synthetic N``: trains the SYNTHETIC demo model and replays N generated events (no data needed).
* ``--run RUN --runs-dir DIR --data CSV --schema ID [--eval-csv CSV]``: an existing experiment run
  (for example the NSL-KDD Random Forest) and a labelled CSV (for example KDDTest+).

Usage:
  python tools/benchmark_deployment.py --synthetic 100000 --out docs/results/benchmark-synthetic.json
  python tools/benchmark_deployment.py --run nsl-kdd-rf-... --runs-dir experiments/runs \\
      --data data/processed/nsl-kdd/KDDTest+.csv --schema nsl-kdd@1.0.0 --out docs/results/benchmark-nsl-kdd.json
Set --database-url to benchmark PostgreSQL (the database must be empty; it is migrated first).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import secrets
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PASSWORD = "pw-" + secrets.token_urlsafe(18)  # throwaway account in a temporary database


def _check(ok: bool, detail: object) -> None:
    if not ok:
        raise RuntimeError(f"benchmark step failed: {detail}")


def _machine() -> dict:
    cpu = platform.processor() or ""
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    mem_gb = None
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal"):
                mem_gb = round(int(line.split()[1]) / 1024 / 1024, 1)
    except OSError:
        pass
    try:
        usable = len(os.sched_getaffinity(0))
    except AttributeError:
        usable = os.cpu_count()
    return {"os": platform.platform(), "python": platform.python_version(), "cpu": cpu,
            "logical_cpus": os.cpu_count(), "usable_cpus": usable, "memory_gb": mem_gb}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--synthetic", type=int, help="replay this many SYNTHETIC events")
    ap.add_argument("--run"), ap.add_argument("--runs-dir"), ap.add_argument("--data"), ap.add_argument("--schema")
    ap.add_argument("--eval-csv", help="labelled CSV for the approval evaluation (default: --data)")
    ap.add_argument("--reference-csv", help="CSV used as the drift reference window (default: the evaluation import)")
    ap.add_argument("--provenance", default="controlled_experiment")
    ap.add_argument("--database-url")
    ap.add_argument("--explanations", type=int, default=20, help="alert explanations to time")
    ap.add_argument("--max-import-rows", type=int, help="raise the import row limit (default: the application's)")
    ap.add_argument("--out")
    a = ap.parse_args()
    # Paths given on the command line are relative to where the tool was started; the application's
    # default config paths (configs/...) are relative to the repository.
    for name in ("runs_dir", "data", "eval_csv", "reference_csv", "out"):
        if getattr(a, name):
            setattr(a, name, str(Path(getattr(a, name)).resolve()))
    os.chdir(REPO)

    from fastapi.testclient import TestClient

    from adaptive_ids import __version__
    from adaptive_ids.api import create_app
    from adaptive_ids.cli import main as cli
    from adaptive_ids.experiments.environment import peak_memory_mb
    from adaptive_ids.db import make_engine, make_session_factory, session_scope
    from adaptive_ids.services import auth
    from adaptive_ids.settings import Settings

    work = Path(tempfile.mkdtemp(prefix="aids-bench-"))
    try:
        if a.synthetic:
            from adaptive_ids.experiments import run_experiment
            from adaptive_ids.research import write_synthetic_dataset

            train = work / "flows_SYNTHETIC_train.csv"
            write_synthetic_dataset(train, n_rows=5000, seed=7)
            replay = work / "flows_SYNTHETIC_replay.csv"
            write_synthetic_dataset(replay, n_rows=a.synthetic, seed=11)
            cfg = json.loads((REPO / "configs/experiments/synthetic-demo.json").read_text())
            cfg = dict(cfg, experiment_id="bench-synthetic", output_dir=str(work / "runs"),
                       dataset=dict(cfg["dataset"], path=str(train)),
                       evaluation=dict(cfg["evaluation"], benchmark={"enabled": False}))
            (work / "cfg.json").write_text(json.dumps(cfg))
            run_name = Path(run_experiment(work / "cfg.json", base_dir=REPO)["run_dir"]).name
            reference = work / "flows_SYNTHETIC_reference.csv"
            write_synthetic_dataset(reference, n_rows=min(a.synthetic, 20000), seed=12)
            runs_dir, data, eval_csv = work / "runs", replay, reference
            schema, provenance, label = "synthetic-flows-demo@1.1.0", "synthetic_demo", f"SYNTHETIC replay ({a.synthetic:,} events)"
        else:
            if not (a.run and a.runs_dir and a.data and a.schema):
                ap.error("--run, --runs-dir, --data and --schema are required without --synthetic")
            run_name, runs_dir, data = a.run, Path(a.runs_dir), Path(a.data)
            eval_csv = Path(a.eval_csv or a.data)
            schema, provenance, label = a.schema, a.provenance, data.name

        url = a.database_url or f"sqlite:///{work / 'bench.db'}"
        os.environ["ADAPTIVE_IDS_DATABASE_URL"] = url
        cli(["db-upgrade"])
        settings = Settings(database_url=url, storage_dir=work / "storage", runs_dir=runs_dir,
                            schemas_dir=REPO / "configs/schemas", max_upload_mb=2000,
                            **({"max_import_rows": a.max_import_rows} if a.max_import_rows else {}))
        with session_scope(make_session_factory(make_engine(url))) as db:
            auth.create_user(db, "bench", PASSWORD, "admin")

        steps: dict[str, dict] = {}

        def timed(name: str, fn, events: int | None = None):
            t0 = time.perf_counter()
            out = fn()
            dt = time.perf_counter() - t0
            steps[name] = {"seconds": round(dt, 3), **({"events": events, "events_per_second": round(events / dt)}
                                                         if events else {})}
            return out

        with TestClient(create_app(settings)) as c:
            h = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"username": "bench", "password": PASSWORD}).json()["access_token"]}

            def upload(path: Path, name: str) -> dict:
                with open(path, "rb") as fh:
                    r = c.post("/api/imports", headers=h, files={"file": (path.name, fh, "text/csv")},
                               data={"schema_id": schema, "dataset_name": name, "dataset_version": "bench",
                                     "provenance": provenance})
                _check(r.status_code == 202, r.text)
                rec = c.get(f"/api/imports/{r.json()['id']}", headers=h).json()
                _check(rec["status"] == "completed", rec)
                return rec

            mv = c.post("/api/models/register-run", json={"run_name": run_name}, headers=h).json()
            ev_import = upload(eval_csv, "evaluation") if eval_csv != data else None
            imp = timed("import", lambda: upload(data, "replay"), None)
            steps["import"].update(events=imp["accepted_rows"], events_per_second=round(imp["accepted_rows"] / steps["import"]["seconds"]),
                                   file_mb=round(data.stat().st_size / 1e6, 1))
            ev_id = (ev_import or imp)["id"]

            def evaluate():
                r = c.post(f"/api/models/{mv['id']}/evaluations", json={"import_id": ev_id}, headers=h)
                _check(r.status_code == 202, r.text)
                return c.get(f"/api/evaluations/{r.json()['id']}", headers=h).json()

            ev = timed("evaluate_candidate", evaluate, None)
            steps["evaluate_candidate"].update(events=ev["results"]["counts"]["compared_events"], verdict=ev["verdict"])
            timed("approve_with_restore_check", lambda: c.post(f"/api/models/{mv['id']}/approve", headers=h,
                  json={"reason": "benchmark run on a passing evaluation"}).raise_for_status())
            timed("activate", lambda: c.post(f"/api/models/{mv['id']}/activate", headers=h,
                  json={"reason": "benchmark"}).raise_for_status())

            def score():
                r = c.post(f"/api/imports/{imp['id']}/score", json={}, headers=h)
                run = c.get(f"/api/scoring-runs/{r.json()['id']}", headers=h).json()
                _check(run["status"] == "completed", run)
                return run

            run = timed("score", score, imp["accepted_rows"])
            steps["score"].update(alerts_created=run["alerts_created"])
            alerts = c.get("/api/alerts", params={"limit": a.explanations}, headers=h).json()["items"]
            lat = []
            for al in alerts:
                t0 = time.perf_counter()
                c.get(f"/api/alerts/{al['id']}/explanation", headers=h).raise_for_status()
                lat.append(time.perf_counter() - t0)
            if lat:
                lat.sort()
                steps["alert_explanation_first_view"] = {"count": len(lat), "median_ms": round(lat[len(lat) // 2] * 1000, 1),
                                                         "max_ms": round(lat[-1] * 1000, 1)}
                t0 = time.perf_counter()
                c.get(f"/api/alerts/{alerts[0]['id']}/explanation", headers=h).raise_for_status()
                steps["alert_explanation_stored"] = {"ms": round((time.perf_counter() - t0) * 1000, 1)}
            n = imp["accepted_rows"]
            ref = timed("import_reference", lambda: upload(Path(a.reference_csv), "reference")) if a.reference_csv else (ev_import or imp)
            if a.reference_csv:
                steps["import_reference"].update(events=ref["accepted_rows"],
                                                 events_per_second=round(ref["accepted_rows"] / steps["import_reference"]["seconds"]))
            n_ref = ref["accepted_rows"]

            def drift():
                body = {"name": "benchmark", "reference": {"import_id": ref["id"]}, "current": {"import_id": imp["id"]},
                        "window": {"mode": "events", "size": max(500, n // 20)}}
                r = c.post("/api/drift/analyses", json=body, headers=h)
                _check(r.status_code == 202, r.text)
                d = c.get(f"/api/drift/analyses/{r.json()['id']}", headers=h).json()
                _check(d["status"] == "completed", d)
                return d

            timed("drift_analysis", drift, n + n_ref)
            timed("dashboard_summary", lambda: c.get("/api/dashboard/summary", headers=h).raise_for_status())

        os.environ["ADAPTIVE_IDS_STORAGE_DIR"] = str(work / "storage")
        os.environ["ADAPTIVE_IDS_RUNS_DIR"] = str(runs_dir)
        timed("backup", lambda: cli(["data-backup", str(work / "backups")]))
        backup_dir = next((work / "backups").iterdir())
        db_file = work / "bench.db"
        db_mb = round(db_file.stat().st_size / 1e6, 1) if db_file.is_file() else None
        if url.startswith("postgresql"):
            from sqlalchemy import text

            with make_engine(url).connect() as conn:
                db_mb = round(conn.execute(text("SELECT pg_database_size(current_database())")).scalar() / 1e6, 1)
        result = {
            "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "app_version": __version__, "machine": _machine(),
            "database": "postgresql" if url.startswith("postgresql") else "sqlite",
            "dataset": label, "provenance": provenance, "model_run": run_name, "steps": steps,
            "peak_process_memory_mb": peak_memory_mb(),
            "storage": {
                "database_mb": db_mb,
                "uploads_mb": round(sum(p.stat().st_size for p in (work / "storage").rglob("*") if p.is_file()) / 1e6, 1),
                "backup_mb": round(sum(p.stat().st_size for p in backup_dir.rglob("*") if p.is_file()) / 1e6, 1),
            },
            "notes": [
                "One process; the API's background work runs inside the request in the test client, so each step's "
                "time is the full server-side work for that step.",
                "Peak memory is the whole benchmark process (application, test client and data generation).",
            ],
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)
    text = json.dumps(result, indent=2)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
