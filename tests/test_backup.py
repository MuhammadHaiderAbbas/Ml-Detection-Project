"""Phase 7: backup and recovery round trip (SQLite by default, PostgreSQL with TEST_DATABASE_URL)."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from api_support import ADMIN_PW, ANALYST_PW, REPO, demo_runs, env, scored_import  # noqa: F401
from sqlalchemy import func, select

from adaptive_ids.db import make_engine, make_session_factory, session_scope
from adaptive_ids.db.models import Alert, DatasetImport, Event, ModelVersion
from adaptive_ids.services import backup
from adaptive_ids.services.backup import BackupError


def _counts(url):
    engine = make_engine(url)
    try:
        with session_scope(make_session_factory(engine)) as db:
            return {m.__name__: db.scalar(select(func.count()).select_from(m)) for m in (DatasetImport, Event, Alert, ModelVersion)}
    finally:
        engine.dispose()


@pytest.fixture
def populated(env, tmp_path):
    admin, analyst = env.login("admin", ADMIN_PW), env.login("analyst", ANALYST_PW)
    scored_import(env, admin, analyst)
    runs = tmp_path / "runs-copy"  # never touch the session-wide runs folder
    shutil.copytree(env.settings.runs_dir, runs)
    return replace(env.settings, runs_dir=runs)


def test_backup_verify_and_restore_round_trip(env, populated, tmp_path):
    settings = populated
    before = _counts(settings.database_url)
    out = backup.create(settings, tmp_path / "backups", configs_dir=REPO / "configs")
    manifest = json.loads((out / "manifest.json").read_text())
    paths = {f["path"] for f in manifest["files"]}
    assert manifest["schema_revision"] == "0004" and manifest["database"] in ("sqlite", "postgresql")
    assert any(p.startswith("storage/") for p in paths) and any(p.endswith(".joblib") for p in paths)
    assert "configs/evaluation-protocol.json" in paths
    assert "password" not in (out / "manifest.json").read_text().lower()
    assert backup.verify(out)["ok"]

    # refuses to overwrite live data without force
    with pytest.raises(BackupError, match="force"):
        backup.restore(settings, out)

    # disaster: the uploads are gone and the database is emptied
    env.client.app.state.engine.dispose()  # Windows cannot replace a SQLite file with open connections
    env.factory.kw["bind"].dispose()
    shutil.rmtree(settings.storage_dir)
    if manifest["database"] == "sqlite":
        Path(settings.database_url.split(":///", 1)[1]).unlink()
    else:
        from sqlalchemy import text

        eng = make_engine(settings.database_url)
        with eng.begin() as c:
            c.execute(text("TRUNCATE dataset_imports, model_versions CASCADE"))
        eng.dispose()
        assert _counts(settings.database_url)["Event"] == 0
    res = backup.restore(settings, out, force=True)
    assert _counts(settings.database_url) == before
    assert any(Path(settings.storage_dir).rglob("*.csv"))
    assert res["models"] and all(m["ok"] and not m["partial"] for m in res["models"])


def test_tampered_backup_is_rejected(env, populated, tmp_path):
    out = backup.create(populated, tmp_path / "b", configs_dir=REPO / "configs")
    victim = next(p for p in out.rglob("*.csv"))
    victim.write_bytes(victim.read_bytes() + b"\n1,2,3")
    (out / "storage" / "planted.txt").write_text("x")
    res = backup.verify(out)
    assert not res["ok"] and any(p.startswith("changed:") for p in res["problems"])
    assert any(p.startswith("not in manifest:") for p in res["problems"])
    with pytest.raises(BackupError, match="verification"):
        backup.restore(populated, out, force=True)


def test_cli_backup_and_verify(env, populated, tmp_path, monkeypatch, capsys):
    from adaptive_ids.cli import main

    for k, v in {"ADAPTIVE_IDS_DATABASE_URL": populated.database_url, "ADAPTIVE_IDS_STORAGE_DIR": str(populated.storage_dir),
                 "ADAPTIVE_IDS_RUNS_DIR": str(populated.runs_dir)}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.chdir(REPO)
    assert main(["data-backup", str(tmp_path / "cli")]) == 0
    folder = next((tmp_path / "cli").iterdir())
    assert main(["data-backup", "--verify", str(folder)]) == 0
    assert "encrypted" in capsys.readouterr().out
