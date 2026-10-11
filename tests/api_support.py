"""Shared fixtures for API tests.

Set TEST_DATABASE_URL (e.g. postgresql+psycopg://...) to run the API tests
against PostgreSQL; by default each test gets a fresh SQLite file.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from adaptive_ids.api import create_app
from adaptive_ids.db import make_engine, make_session_factory, session_scope
from adaptive_ids.experiments import run_experiment
from adaptive_ids.research import write_synthetic_dataset
from adaptive_ids.services import auth
from adaptive_ids.settings import Settings

REPO = Path(__file__).resolve().parents[1]
ADMIN_PW = "admin-password-123"
ANALYST_PW = "analyst-password-123"


def alembic(url: str, action: str) -> None:
    cfg = Config(str(REPO / "alembic.ini"))
    cfg.attributes["database_url"] = url
    cfg.attributes["configure_logger"] = False
    if action == "upgrade":
        command.upgrade(cfg, "head")
    else:
        command.downgrade(cfg, "base")


@pytest.fixture(scope="session")
def demo_runs(tmp_path_factory):
    """Two trained SYNTHETIC experiment runs plus a replay CSV, shared by all API tests."""
    base = tmp_path_factory.mktemp("runs")
    train = base / "flows_SYNTHETIC_train.csv"
    write_synthetic_dataset(train, n_rows=1500, seed=7)
    replay = base / "flows_SYNTHETIC_replay.csv"
    write_synthetic_dataset(replay, n_rows=600, seed=11)
    replay_drift = base / "flows_SYNTHETIC_replay_drift.csv"
    write_synthetic_dataset(replay_drift, n_rows=1200, seed=12, drift_after_fraction=0.5, drift_strength=0.8)
    cfg = json.loads((REPO / "configs/experiments/synthetic-demo.json").read_text())
    names = []
    for exp_id, n_est in (("api-demo-a", 20), ("api-demo-b", 10)):
        c = dict(cfg, experiment_id=exp_id, output_dir=str(base / "runs"),
                 dataset=dict(cfg["dataset"], path=str(train)),
                 model=dict(cfg["model"], params=dict(cfg["model"]["params"], n_estimators=n_est)),
                 evaluation=dict(cfg["evaluation"], benchmark={"enabled": False}))
        p = base / f"{exp_id}.json"
        p.write_text(json.dumps(c))
        names.append(Path(run_experiment(p, base_dir=REPO)["run_dir"]).name)
    return {"runs_dir": base / "runs", "run_names": names, "replay": replay, "replay_drift": replay_drift}


@dataclass
class Env:
    client: TestClient
    settings: Settings
    factory: object
    runs: dict

    def login(self, username: str, password: str) -> dict:
        r = self.client.post("/api/auth/login", json={"username": username, "password": password})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def env(tmp_path, demo_runs):
    url = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'test.db'}"
    alembic(url, "upgrade")
    settings = Settings(
        database_url=url,
        storage_dir=tmp_path / "storage",
        schemas_dir=REPO / "configs/schemas",
        runs_dir=demo_runs["runs_dir"],
        severity_rules_path=REPO / "configs/severity-rules.json",
        max_upload_mb=2,
    )
    engine = make_engine(url)
    factory = make_session_factory(engine)
    with session_scope(factory) as db:
        auth.create_user(db, "admin", ADMIN_PW, "admin")
        auth.create_user(db, "analyst", ANALYST_PW, "analyst")
    app = create_app(settings)
    with TestClient(app) as client:
        yield Env(client, settings, factory, demo_runs)
    app.state.engine.dispose()
    engine.dispose()
    if os.environ.get("TEST_DATABASE_URL"):
        alembic(url, "downgrade")


def activate_model(e: Env, admin: dict, run_index: int = 0) -> dict:
    r = e.client.post("/api/models/register-run", json={"run_name": e.runs["run_names"][run_index]}, headers=admin)
    assert r.status_code == 201, r.text
    mid = r.json()["id"]
    assert e.client.post(f"/api/models/{mid}/approve", json={"reason": "test approval"}, headers=admin).status_code == 200
    r = e.client.post(f"/api/models/{mid}/activate", json={"reason": "test activation"}, headers=admin)
    assert r.status_code == 200, r.text
    return r.json()


def upload(e: Env, headers: dict, path: Path | None = None, **form) -> dict:
    path = path or e.runs["replay"]
    data = {"schema_id": "synthetic-flows-demo@1.1.0", "dataset_name": "replay", "dataset_version": "seed11",
            "provenance": "synthetic_demo", **form}
    with open(path, "rb") as fh:
        r = e.client.post("/api/imports", files={"file": (path.name, fh, "text/csv")}, data=data, headers=headers)
    return r


def scored_import(e: Env, admin: dict, analyst: dict) -> int:
    activate_model(e, admin)
    r = upload(e, analyst)
    assert r.status_code == 202, r.text
    import_id = r.json()["id"]
    assert e.client.get(f"/api/imports/{import_id}", headers=analyst).json()["status"] == "completed"
    r = e.client.post(f"/api/imports/{import_id}/score", json={}, headers=analyst)
    assert r.status_code == 202, r.text
    run = e.client.get(f"/api/scoring-runs/{r.json()['id']}", headers=analyst).json()
    assert run["status"] == "completed", run
    return import_id
