import csv
import io

from api_support import ADMIN_PW, ANALYST_PW, activate_model, demo_runs, env, scored_import, upload  # noqa: F401
from sqlalchemy import select

from adaptive_ids.db.models import AuditLog, ModelVersion, Prediction


def test_health_needs_no_auth(env):
    r = env.client.get("/api/health")
    assert r.status_code == 200 and r.json()["database"] == "ok"


# --------------------------------------------------------------------------- auth & permissions


def test_login_logout_and_failed_login_audited(env):
    r = env.client.post("/api/auth/login", json={"username": "admin", "password": "wrong-password"})
    assert r.status_code == 401 and r.json()["detail"] == "invalid username or password"
    r = env.client.post("/api/auth/login", json={"username": "nobody", "password": "wrong-password"})
    assert r.status_code == 401 and r.json()["detail"] == "invalid username or password"  # no user enumeration
    h = env.login("admin", ADMIN_PW)
    assert env.client.get("/api/auth/me", headers=h).json()["username"] == "admin"
    assert env.client.post("/api/auth/logout", headers=h).status_code == 204
    assert env.client.get("/api/auth/me", headers=h).status_code == 401
    with env.factory() as db:
        actions = [a.action for a in db.scalars(select(AuditLog).order_by(AuditLog.id))]
    assert actions.count("auth.login_failed") == 2 and "auth.login" in actions and "auth.logout" in actions


def test_requests_without_valid_token_rejected(env):
    assert env.client.get("/api/alerts").status_code == 401
    assert env.client.get("/api/alerts", headers={"Authorization": "Bearer forged"}).status_code == 401
    assert env.client.get("/api/alerts", headers={"Authorization": "Basic abc"}).status_code == 401


def test_role_checks_are_server_side(env):
    analyst = env.login("analyst", ANALYST_PW)
    admin = env.login("admin", ADMIN_PW)
    new = {"username": "bob", "password": "long-enough-password", "role": "analyst"}
    assert env.client.post("/api/users", json=new, headers=analyst).status_code == 403
    assert env.client.get("/api/audit-logs", headers=analyst).status_code == 403
    assert env.client.post("/api/models/register-run", json={"run_name": env.runs["run_names"][0]},
                           headers=analyst).status_code == 403
    assert env.client.post("/api/users", json=new, headers=admin).status_code == 201
    assert env.client.post("/api/users", json=new, headers=admin).status_code == 409
    weak = dict(new, username="carol", password="short")
    assert env.client.post("/api/users", json=weak, headers=admin).status_code == 422


def test_deactivation_revokes_sessions(env):
    admin = env.login("admin", ADMIN_PW)
    analyst = env.login("analyst", ANALYST_PW)
    uid = env.client.get("/api/auth/me", headers=analyst).json()["id"]
    assert env.client.patch(f"/api/users/{uid}", json={"is_active": False}, headers=admin).status_code == 200
    assert env.client.get("/api/auth/me", headers=analyst).status_code == 401
    r = env.client.post("/api/auth/login", json={"username": "analyst", "password": ANALYST_PW})
    assert r.status_code == 401


# --------------------------------------------------------------------------- model governance


def test_model_lifecycle_requires_explicit_approval_and_supports_rollback(env):
    admin = env.login("admin", ADMIN_PW)
    a, b = env.runs["run_names"]
    m1 = env.client.post("/api/models/register-run", json={"run_name": a}, headers=admin).json()
    assert m1["status"] == "candidate" and m1["evaluation"]["test"]["n_scored"] > 0
    assert m1["provenance"] == "synthetic_demo"
    # cannot activate a candidate, cannot approve without a reason
    assert env.client.post(f"/api/models/{m1['id']}/activate", json={"reason": "x"}, headers=admin).status_code == 409
    assert env.client.post(f"/api/models/{m1['id']}/approve", json={"reason": ""}, headers=admin).status_code == 422
    assert env.client.post("/api/models/register-run", json={"run_name": a}, headers=admin).status_code == 409
    assert env.client.post("/api/models/register-run", json={"run_name": "../../etc"}, headers=admin).status_code == 400

    activate_model(env, admin, run_index=1)  # m2 becomes active
    m1_id = m1["id"]
    env.client.post(f"/api/models/{m1_id}/approve", json={"reason": "ok"}, headers=admin)
    env.client.post(f"/api/models/{m1_id}/activate", json={"reason": "switch"}, headers=admin)
    models = {m["version_id"]: m["status"] for m in env.client.get("/api/models", headers=admin).json()}
    assert sorted(models.values()) == ["active", "archived"]
    # roll back to the previously approved, now archived version
    archived = next(m for m in env.client.get("/api/models", headers=admin).json() if m["status"] == "archived")
    r = env.client.post(f"/api/models/{archived['id']}/activate", json={"reason": "rollback test"}, headers=admin)
    assert r.status_code == 200 and r.json()["status"] == "active"
    assert env.client.get("/api/models/active", headers=admin).json()["id"] == archived["id"]
    hist = env.client.get(f"/api/models/{archived['id']}/history", headers=admin).json()
    assert [h["to_status"] for h in hist] == ["candidate", "approved", "active", "archived", "active"]
    logs = env.client.get("/api/audit-logs", params={"action": "model.rollback"}, headers=admin).json()
    assert logs["total"] == 1


def test_rejected_model_cannot_be_activated(env):
    admin = env.login("admin", ADMIN_PW)
    m = env.client.post("/api/models/register-run", json={"run_name": env.runs["run_names"][0]}, headers=admin).json()
    assert env.client.post(f"/api/models/{m['id']}/reject", json={"reason": "not good"}, headers=admin).status_code == 200
    assert env.client.post(f"/api/models/{m['id']}/approve", json={"reason": "x"}, headers=admin).status_code == 409
    assert env.client.post(f"/api/models/{m['id']}/activate", json={"reason": "x"}, headers=admin).status_code == 409


# --------------------------------------------------------------------------- imports


def test_import_records_and_rejected_rows(env):
    analyst = env.login("analyst", ANALYST_PW)
    r = upload(env, analyst)
    assert r.status_code == 202 and r.json()["status"] == "queued"
    rec = env.client.get(f"/api/imports/{r.json()['id']}", headers=analyst).json()
    assert rec["status"] == "completed"
    assert (rec["total_rows"], rec["rejected_rows"]) == (600, 6)
    assert rec["accepted_rows"] == 594 and len(rec["file_sha256"]) == 64
    assert rec["schema_id"] == "synthetic-flows-demo@1.1.0"
    rej = env.client.get(f"/api/imports/{rec['id']}/rejected-rows", headers=analyst).json()
    assert rej["total"] == 6 and all(row["reasons"] for row in rej["items"])
    ev = env.client.get("/api/events", params={"import_id": rec["id"], "limit": 1}, headers=analyst).json()
    e = ev["items"][0]
    assert ev["total"] == 594 and e["source"].startswith("10.0.") and e["destination"].startswith("192.0.2.")
    assert set(e["features"]) == {f for f in e["features"]} and "Label" not in e["features"]
    assert e["occurred_at"].endswith("Z") or e["occurred_at"].endswith("+00:00")


def test_upload_validation(env, tmp_path):
    analyst = env.login("analyst", ANALYST_PW)
    txt = tmp_path / "x.txt"
    txt.write_text("a,b\n1,2\n")
    assert upload(env, analyst, txt).status_code == 400
    binary = tmp_path / "bin.csv"
    binary.write_bytes(b"\x00\x01\x02" * 100)
    assert upload(env, analyst, binary).status_code == 400
    big = tmp_path / "big.csv"
    big.write_text("a\n" + "1\n" * 1_200_000)  # > 2 MB limit in the test settings
    assert "limit" in upload(env, analyst, big).json()["detail"]
    assert upload(env, analyst, schema_id="nope@1").status_code == 400
    assert upload(env, analyst, provenance="original_dissertation").status_code == 400
    assert upload(env, analyst, column_mapping="{not json").status_code == 400
    # nothing was left behind in storage for rejected uploads
    assert not list((env.settings.storage_dir / "uploads").glob("*"))


def test_incompatible_file_fails_import_with_reason(env, tmp_path):
    analyst = env.login("analyst", ANALYST_PW)
    bad = tmp_path / "bad.csv"
    bad.write_text("Flow ID,Label\nx,Benign\n")
    rec = upload(env, analyst, bad).json()
    rec = env.client.get(f"/api/imports/{rec['id']}", headers=analyst).json()
    assert rec["status"] == "failed" and "missing=" in rec["errors"][0]


# --------------------------------------------------------------------------- scoring & alerts


def test_scoring_creates_traceable_predictions_and_alerts(env):
    admin, analyst = env.login("admin", ADMIN_PW), env.login("analyst", ANALYST_PW)
    import_id = scored_import(env, admin, analyst)
    runs = env.client.get("/api/scoring-runs", params={"import_id": import_id}, headers=analyst).json()
    run = runs[0]
    assert run["events_total"] == 594 and run["events_scored"] == 594
    assert run["alerts_created"] == run["suspicious"] > 0
    assert "not analyst-confirmed" in run["label_metrics"]["basis"]
    # same import + same model cannot be scored twice
    assert env.client.post(f"/api/imports/{import_id}/score", json={}, headers=analyst).status_code == 409

    alerts = env.client.get("/api/alerts", params={"import_id": import_id, "limit": 500}, headers=analyst).json()
    assert alerts["total"] == run["alerts_created"]
    assert all(a["status"] == "new" for a in alerts["items"])
    d = env.client.get(f"/api/alerts/{alerts['items'][0]['id']}", headers=analyst).json()
    assert d["prediction"]["model_version_id"] == d["model"]["id"]
    assert d["prediction"]["preprocessing_version"] == d["model"]["preprocessing_version"]
    assert d["prediction"]["score_kind"].endswith("uncalibrated")
    assert d["prediction"]["predicted_class"] != "Benign"
    assert "neither confirms an attack" in d["interpretation"]
    assert d["history"][0]["changed_by"] == "system" and d["history"][0]["to_status"] == "new"
    ev = env.client.get(f"/api/events/{d['event']['id']}", headers=analyst).json()
    assert len(ev["predictions"]) == 1


def test_scoring_requires_active_model(env):
    analyst = env.login("analyst", ANALYST_PW)
    import_id = upload(env, analyst).json()["id"]
    r = env.client.post(f"/api/imports/{import_id}/score", json={}, headers=analyst)
    assert r.status_code == 409 and "no active model" in r.json()["detail"]


def test_tampered_model_fails_scoring_without_predictions(env):
    admin, analyst = env.login("admin", ADMIN_PW), env.login("analyst", ANALYST_PW)
    activate_model(env, admin)
    with env.factory() as db:
        mv = db.scalar(select(ModelVersion))
        mv.artifact_sha256 = "0" * 64  # registry no longer matches the file on disk
        db.commit()
    import_id = upload(env, analyst).json()["id"]
    run = env.client.post(f"/api/imports/{import_id}/score", json={}, headers=analyst).json()
    run = env.client.get(f"/api/scoring-runs/{run['id']}", headers=analyst).json()
    assert run["status"] == "failed" and "hash mismatch" in run["error"]
    with env.factory() as db:
        assert db.scalar(select(Prediction)) is None


def test_alert_lifecycle(env):
    admin, analyst = env.login("admin", ADMIN_PW), env.login("analyst", ANALYST_PW)
    scored_import(env, admin, analyst)
    aid = env.client.get("/api/alerts", headers=analyst).json()["items"][0]["id"]
    st = lambda s, note=None: env.client.post(f"/api/alerts/{aid}/status", json={"status": s, "note": note}, headers=analyst)
    assert st("resolved", "skip").status_code == 400  # new -> resolved is not allowed
    assert st("investigating").status_code == 200
    assert st("resolved").status_code == 400  # a note is required
    assert st("resolved", "Benign maintenance traffic").status_code == 200
    assert st("investigating", "reopened: new evidence").status_code == 200
    assert st("false_positive", "Scanner run by IT").status_code == 200
    d = env.client.get(f"/api/alerts/{aid}", headers=analyst).json()
    assert [h["to_status"] for h in d["history"]] == ["new", "investigating", "resolved", "investigating", "false_positive"]
    assert d["history"][2]["changed_by"] == "analyst" and d["assignee"] == "analyst"
    assert env.client.post(f"/api/alerts/{aid}/notes", json={"body": "checked firewall logs"}, headers=analyst).status_code == 201
    uid = env.client.get("/api/auth/me", headers=admin).json()["id"]
    assert env.client.post(f"/api/alerts/{aid}/assign", json={"assignee_id": uid}, headers=analyst).json()["assignee_id"] == uid
    assert env.client.post(f"/api/alerts/{aid}/assign", json={"assignee_id": 9999}, headers=analyst).status_code == 400
    assert env.client.get("/api/alerts", params={"status": "false_positive"}, headers=analyst).json()["total"] == 1
    assert env.client.get("/api/alerts", params={"status": "bogus"}, headers=analyst).status_code == 400


def test_alert_groups_filters_and_export(env):
    admin, analyst = env.login("admin", ADMIN_PW), env.login("analyst", ANALYST_PW)
    scored_import(env, admin, analyst)
    total = env.client.get("/api/alerts", headers=analyst).json()["total"]
    groups = env.client.get("/api/alerts/groups", params={"limit": 500}, headers=analyst).json()
    assert sum(g["alerts"] for g in groups["items"]) == total
    g = groups["items"][0]
    by_key = env.client.get("/api/alerts", params={"group_key": g["group_key"]}, headers=analyst).json()
    assert by_key["total"] == g["alerts"]
    by_dst = env.client.get("/api/alerts", params={"destination": g["destination"]}, headers=analyst).json()
    assert by_dst["total"] >= g["alerts"]
    r = env.client.get("/api/alerts/export.csv", headers=analyst)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0][0] == "id" and len([x for x in rows[1:] if x and x[0].isdigit()]) == total
    assert "uncalibrated" in r.text


def test_incident_workflow_and_confirmed_counts(env):
    admin, analyst = env.login("admin", ADMIN_PW), env.login("analyst", ANALYST_PW)
    scored_import(env, admin, analyst)
    s = env.client.get("/api/dashboard/summary", headers=analyst).json()
    assert s["confirmed_attacks"] is None and "Unavailable" in s["confirmed_attacks_note"]
    ids = [a["id"] for a in env.client.get("/api/alerts", params={"limit": 3}, headers=analyst).json()["items"]]
    inc = env.client.post("/api/incidents", json={"title": "Possible DoS burst", "alert_ids": ids[:2]}, headers=analyst)
    assert inc.status_code == 201
    inc_id = inc.json()["incident"]["id"]
    other = env.client.post("/api/incidents", json={"title": "Other", "alert_ids": [ids[0]]}, headers=analyst)
    assert other.status_code == 409  # alert already belongs to an incident
    assert env.client.post(f"/api/incidents/{inc_id}/alerts", json={"alert_ids": [ids[2]]}, headers=analyst).status_code == 200
    upd = lambda body: env.client.patch(f"/api/incidents/{inc_id}", json=body, headers=analyst)
    assert upd({"status": "closed"}).status_code == 400  # needs a disposition first
    assert upd({"disposition": "confirmed_attack"}).status_code == 400  # needs a decision note
    assert upd({"status": "investigating"}).status_code == 200
    assert env.client.post(f"/api/incidents/{inc_id}/notes", json={"body": "pcap reviewed", "kind": "evidence"},
                           headers=analyst).status_code == 201
    r = upd({"disposition": "confirmed_attack", "decision_note": "Matches lab DoS exercise schedule"})
    assert r.status_code == 200
    r = upd({"status": "closed"})
    d = r.json()
    assert d["incident"]["status"] == "closed" and d["incident"]["closed_at"]
    assert len(d["alerts"]) == 3
    kinds = [t["kind"] for t in d["timeline"]]
    assert "decision" in kinds and "evidence" in kinds and "event" in kinds
    md = env.client.get(f"/api/incidents/{inc_id}/export.md", headers=analyst)
    assert md.status_code == 200 and "Disposition (analyst decision): confirmed_attack" in md.text
    s = env.client.get("/api/dashboard/summary", headers=analyst).json()
    assert s["confirmed_attacks"] == 1
    assert env.client.post(f"/api/incidents/{inc_id}/alerts", json={"alert_ids": [ids[0]]}, headers=analyst).status_code == 409


def test_dashboard_counts_match_records(env):
    admin, analyst = env.login("admin", ADMIN_PW), env.login("analyst", ANALYST_PW)
    import_id = scored_import(env, admin, analyst)
    s = env.client.get("/api/dashboard/summary", headers=analyst).json()
    run = env.client.get("/api/scoring-runs", headers=analyst).json()[0]
    assert s["events_processed"] == 594 and s["events_scored"] == run["events_scored"]
    assert s["suspicious_predictions"] == run["suspicious"] == sum(s["alerts_by_status"].values())
    assert s["demo_data_present"] is True
    assert s["active_model"]["provenance"] == "synthetic_demo"
    assert s["processing_latency"]["events"] == 594
    assert s["top_destinations"] and all(d["value"].startswith("192.0.2.") for d in s["top_destinations"])
    assert set(s["definitions"]) >= {"events_processed", "suspicious_predictions", "confirmed_attacks"}
    filtered = env.client.get("/api/dashboard/summary", params={"import_id": import_id + 999}, headers=analyst).json()
    assert filtered["events_processed"] == 0 and filtered["suspicious_predictions"] == 0


def test_audit_log_records_sensitive_actions(env):
    admin, analyst = env.login("admin", ADMIN_PW), env.login("analyst", ANALYST_PW)
    scored_import(env, admin, analyst)
    actions = {a["action"] for a in env.client.get("/api/audit-logs", params={"limit": 1000}, headers=admin).json()["items"]}
    assert {"user.create", "auth.login", "model.register", "model.approve", "model.activate",
            "import.create", "scoring.start"} <= actions


def test_validation_errors_do_not_echo_input(env):
    r = env.client.post("/api/auth/login", json={"username": "x" * 500, "password": "secret-value"})
    assert r.status_code == 422 and "secret-value" not in r.text and "xxxx" not in r.text
