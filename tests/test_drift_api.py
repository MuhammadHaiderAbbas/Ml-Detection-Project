from api_support import ADMIN_PW, ANALYST_PW, activate_model, demo_runs, env, upload  # noqa: F401


def _import_and_score(e, h, path=None, name="replay"):
    rec = upload(e, h, path, dataset_name=name).json()
    assert e.client.get(f"/api/imports/{rec['id']}", headers=h).json()["status"] == "completed"
    run = e.client.post(f"/api/imports/{rec['id']}/score", json={}, headers=h).json()
    assert e.client.get(f"/api/scoring-runs/{run['id']}", headers=h).json()["status"] == "completed"
    return rec["id"]


def _analysis(e, h, ref, cur, **extra):
    body = {"name": "test", "reference": {"import_id": ref}, "current": {"import_id": cur}, "window": {"mode": "events", "size": 200}, **extra}
    r = e.client.post("/api/drift/analyses", json=body, headers=h)
    assert r.status_code == 202, r.text
    return e.client.get(f"/api/drift/analyses/{r.json()['id']}", headers=h).json()


def test_drift_detected_and_kept_separate_by_type(env):
    admin, analyst = env.login("admin", ADMIN_PW), env.login("analyst", ANALYST_PW)
    activate_model(env, admin)
    ref = _import_and_score(env, analyst)
    cur = _import_and_score(env, analyst, env.runs["replay_drift"], name="drifted")
    a = _analysis(env, analyst, ref, cur)
    assert a["status"] == "completed", a["error"]
    s = a["summary"]
    assert s["feature"]["status"] == "detected"
    assert set(s) >= {"feature", "prediction", "performance", "concept"}
    assert "not evidence of an attack" in s["interpretation"]
    assert a["n_reference"] == 594 and a["n_current"] > 1000
    feats = a["overall"]["features"]
    drifted = [f for f, v in feats.items() if v["severity"] in ("moderate", "major")]
    assert drifted and all(feats[f]["ks_p_adj"] < a["config"]["alpha"] for f in drifted)
    assert "bins" in feats[drifted[0]]  # reference-vs-current distribution for the UI
    wins = env.client.get(f"/api/drift/analyses/{a['id']}/windows", headers=analyst).json()
    assert len(wins) == a["summary"]["n_windows"] and sum(w["n_events"] for w in wins) == a["n_current"]
    # drift starts halfway through the current file: early windows clean, later full windows drifted
    full = [w for w in wins if w["n_events"] >= a["config"]["min_window_events"]]
    assert not full[0]["drifted_features"] and full[-1]["drifted_features"]
    # a short trailing window is reported as insufficient data rather than judged
    short = [w for w in wins if w["n_events"] < a["config"]["min_window_events"]]
    assert all(v["severity"] == "insufficient_data" for w in short for v in w["features"].values())
    ev = env.client.get("/api/drift/events", params={"analysis_id": a["id"]}, headers=analyst).json()
    assert ev["total"] >= 1 and {e["drift_type"] for e in ev["items"]} <= {"feature", "prediction", "performance", "concept"}
    assert all(e["status"] == "new" for e in ev["items"])


def test_no_drift_between_identical_distributions(env):
    admin, analyst = env.login("admin", ADMIN_PW), env.login("analyst", ANALYST_PW)
    activate_model(env, admin)
    imp = _import_and_score(env, analyst)
    a = _analysis(env, analyst, imp, imp)
    assert a["summary"]["feature"]["status"] == "not_detected"
    assert env.client.get("/api/drift/events", params={"analysis_id": a["id"]}, headers=analyst).json()["total"] == 0


def test_drift_never_changes_model_lifecycle(env):
    admin, analyst = env.login("admin", ADMIN_PW), env.login("analyst", ANALYST_PW)
    activate_model(env, admin)
    before = {m["id"]: m["status"] for m in env.client.get("/api/models", headers=admin).json()}
    ref = _import_and_score(env, analyst)
    cur = _import_and_score(env, analyst, env.runs["replay_drift"], name="drifted")
    _analysis(env, analyst, ref, cur)
    after = {m["id"]: m["status"] for m in env.client.get("/api/models", headers=admin).json()}
    assert before == after
    actions = {x["action"] for x in env.client.get("/api/audit-logs", params={"limit": 1000}, headers=admin).json()["items"]}
    assert "drift.analysis_start" in actions and not {"model.activate", "model.approve"} & (actions - {"model.activate", "model.approve"})
    acts = [x["action"] for x in env.client.get("/api/audit-logs", params={"limit": 1000}, headers=admin).json()["items"]]
    assert acts.count("model.activate") == 1  # only the explicit activation in this test


def test_drift_event_lifecycle_and_notes(env):
    admin, analyst = env.login("admin", ADMIN_PW), env.login("analyst", ANALYST_PW)
    activate_model(env, admin)
    ref = _import_and_score(env, analyst)
    cur = _import_and_score(env, analyst, env.runs["replay_drift"], name="drifted")
    a = _analysis(env, analyst, ref, cur)
    eid = env.client.get("/api/drift/events", params={"analysis_id": a["id"]}, headers=analyst).json()["items"][0]["id"]
    st = lambda s, note=None: env.client.post(f"/api/drift/events/{eid}/status", json={"status": s, "note": note}, headers=analyst)
    assert st("acknowledged").status_code == 200
    assert env.client.post(f"/api/drift/events/{eid}/notes", json={"body": "Traffic mix changed after a scheduled backup window."}, headers=analyst).status_code == 201
    assert st("closed").status_code == 400  # outcome note required
    assert st("closed", "Expected seasonal change; no model action.").status_code == 200
    assert st("acknowledged").status_code == 400  # closed -> acknowledged not allowed
    d = env.client.get(f"/api/drift/events/{eid}", headers=analyst).json()
    assert [n["kind"] for n in d["notes"]] == ["status", "note", "status"] and "does not retrain" in d["interpretation"]
    assert env.client.get("/api/drift/events", params={"status": "new", "analysis_id": a["id"]}, headers=analyst).json()["total"] < \
        env.client.get("/api/drift/events", params={"analysis_id": a["id"]}, headers=analyst).json()["total"]


def test_drift_reports_and_dashboard_status(env):
    admin, analyst = env.login("admin", ADMIN_PW), env.login("analyst", ANALYST_PW)
    assert env.client.get("/api/dashboard/summary", headers=analyst).json()["drift_monitoring"]["status"] == "not_configured"
    activate_model(env, admin)
    ref = _import_and_score(env, analyst)
    cur = _import_and_score(env, analyst, env.runs["replay_drift"], name="drifted")
    a = _analysis(env, analyst, ref, cur)
    md = env.client.get(f"/api/drift/analyses/{a['id']}/report.md", headers=analyst)
    assert md.status_code == 200 and "SYNTHETIC DEMONSTRATION DATA" in md.text and "## Verdicts" in md.text
    csv_text = env.client.get(f"/api/drift/analyses/{a['id']}/windows.csv", headers=analyst).text
    assert csv_text.startswith("window_index,") and ",feature," in csv_text
    dm = env.client.get("/api/dashboard/summary", headers=analyst).json()["drift_monitoring"]
    assert dm["status"] == "drift_detected" and dm["open_events"].get("feature", 0) >= 1
    assert dm["latest_analysis"]["id"] == a["id"]


def test_drift_validation(env):
    admin, analyst = env.login("admin", ADMIN_PW), env.login("analyst", ANALYST_PW)
    imp = upload(env, analyst).json()["id"]
    bad = lambda body: env.client.post("/api/drift/analyses", json={"name": "x", "reference": {"import_id": imp}, "current": {"import_id": imp}, **body}, headers=analyst)
    assert bad({"features": ["not a feature"]}).status_code == 400
    assert bad({"config": {"psi_moderate": 0.5, "psi_major": 0.2}}).status_code == 400
    assert bad({"config": {"unknown": 1}}).status_code == 400
    assert bad({"window": {"mode": "events", "size": 5}}).status_code == 422
    assert bad({"current": {"import_id": 9999}}).status_code == 404
    assert bad({"reference": {"import_id": imp, "since": "2026-02-01T00:00:00Z", "until": "2026-01-01T00:00:00Z"}}).status_code == 400
    # without an active model the analysis still runs; prediction drift is reported as not assessable
    a = env.client.post("/api/drift/analyses", json={"name": "no model", "reference": {"import_id": imp}, "current": {"import_id": imp}}, headers=analyst).json()
    a = env.client.get(f"/api/drift/analyses/{a['id']}", headers=analyst).json()
    assert a["status"] == "completed" and a["summary"]["prediction"]["status"] == "not_assessable"
    assert a["summary"]["performance"]["status"] == "not_assessable"
