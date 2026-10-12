"""Phase 7: configurable data retention keeps evidence and accounts for every purge."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from api_support import ADMIN_PW, ANALYST_PW, REPO, activate_model, demo_runs, env, scored_import, upload  # noqa: F401
from sqlalchemy import func, select

from adaptive_ids.db import session_scope
from adaptive_ids.db.models import Alert, AuditLog, DatasetImport, Event, Prediction, SessionToken, utcnow
from adaptive_ids.services import retention
from adaptive_ids.services.retention import RetentionError, RetentionPolicy


def test_shipped_policy_is_valid():
    p = RetentionPolicy.load(REPO / "configs/retention.json")
    assert p.imports_days is None and p.audit_days is None  # nothing is deleted unless configured


@pytest.mark.parametrize("bad", [{"audit_days": 30}, {"imports_days": 0}, {"imports_days": "7"}, {"surprise": 1}])
def test_policy_validation(tmp_path, bad):
    f = tmp_path / "p.json"
    f.write_text(json.dumps(bad))
    with pytest.raises(RetentionError):
        RetentionPolicy.load(f)


def _age(env, import_id, days):
    with session_scope(env.factory) as db:
        db.get(DatasetImport, import_id).created_at = utcnow() - timedelta(days=days)


def _count(env, model, **where):
    with session_scope(env.factory) as db:
        q = select(func.count()).select_from(model)
        for k, v in where.items():
            q = q.where(getattr(model, k) == v)
        return db.scalar(q)


def test_old_imports_are_purged_but_evidence_is_kept(env):
    admin, analyst = env.login("admin", ADMIN_PW), env.login("analyst", ANALYST_PW)
    scored = scored_import(env, admin, analyst)  # activate_model also created the evaluation import (evidence)
    evidence_eval = env.cache["eval_import"]
    linked = upload(env, analyst, dataset_name="linked").json()["id"]
    env.client.post(f"/api/imports/{linked}/score", json={}, headers=analyst)
    alert_id = env.client.get("/api/alerts", params={"import_id": linked, "limit": 1}, headers=analyst).json()["items"][0]["id"]
    env.client.post("/api/incidents", json={"title": "keep me", "alert_ids": [alert_id]}, headers=analyst)
    fresh = upload(env, analyst, dataset_name="fresh").json()["id"]
    for iid in (scored, evidence_eval, linked):
        _age(env, iid, 40)
    assert _count(env, Alert, import_id=scored) > 0
    with session_scope(env.factory) as db:
        stored = Path(db.get(DatasetImport, scored).stored_path)
    assert stored.is_file()

    policy = RetentionPolicy(imports_days=30, sessions_days=None)
    with session_scope(env.factory) as db:
        dry = retention.plan(db, policy)
    assert [r["id"] for r in dry["imports"]] == [scored]
    assert {r["id"]: r["reason"] for r in dry["kept_as_evidence"]} == {
        evidence_eval: "used by a model evaluation", linked: "has alerts linked to an incident"}
    assert _count(env, DatasetImport) == 4  # the dry run deleted nothing

    with session_scope(env.factory) as db:
        res = retention.apply(db, policy)
    assert res["applied"]["imports_deleted"] == 1 and res["applied"]["events_deleted"] == 594
    assert _count(env, DatasetImport, id=scored) == 0 and _count(env, Event, import_id=scored) == 0
    assert _count(env, Alert, import_id=scored) == 0 and not stored.exists()
    assert _count(env, DatasetImport) == 3 and _count(env, Event, import_id=fresh) == 594
    assert _count(env, Alert, import_id=linked) > 0 and _count(env, Prediction) > 0
    with session_scope(env.factory) as db:
        rec = db.scalar(select(AuditLog).where(AuditLog.action == "retention.purge"))
        assert rec.details["imports_deleted"] == 1 and sorted(rec.details["kept_as_evidence"]) == sorted([evidence_eval, linked])


def test_upload_files_are_minimised_without_losing_records(env):
    analyst = env.login("analyst", ANALYST_PW)
    iid = upload(env, analyst).json()["id"]
    _age(env, iid, 31)
    with session_scope(env.factory) as db:
        path = Path(db.get(DatasetImport, iid).stored_path)
        retention.apply(db, RetentionPolicy(upload_files_days=30, sessions_days=None))
    assert not path.exists() and _count(env, Event, import_id=iid) == 594
    with session_scope(env.factory) as db:
        assert "removed by retention policy" in db.get(DatasetImport, iid).warnings[-1]


def test_audit_and_session_purge(env):
    env.login("analyst", ANALYST_PW)
    with session_scope(env.factory) as db:
        old = AuditLog(action="test.old", details={}, at=utcnow() - timedelta(days=400))
        db.add(old)
        for s in db.scalars(select(SessionToken)):
            s.revoked_at = utcnow() - timedelta(days=45)
    with session_scope(env.factory) as db:
        res = retention.apply(db, RetentionPolicy(audit_days=365, sessions_days=30))
    assert res["applied"]["audit_records_deleted"] == 1 and res["applied"]["sessions_deleted"] >= 1
    assert _count(env, AuditLog, action="test.old") == 0 and _count(env, AuditLog, action="auth.login") >= 1
    assert _count(env, SessionToken) == 0


def test_cli_dry_run(env, monkeypatch, capsys):
    from adaptive_ids.cli import main

    monkeypatch.setenv("ADAPTIVE_IDS_DATABASE_URL", env.settings.database_url)
    assert main(["retention", "--policy", str(REPO / "configs/retention.json")]) == 0
    out = capsys.readouterr().out
    assert "Dry run: nothing was deleted" in out and '"imports": []' in out
