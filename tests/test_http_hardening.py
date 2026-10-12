"""Phase 7: security headers, request size limits, safe errors and export escaping."""

from __future__ import annotations

from api_support import ADMIN_PW, ANALYST_PW, demo_runs, env  # noqa: F401

from adaptive_ids.textsafety import csv_cell


def test_security_headers_on_api_and_errors(env):
    for r in (env.client.get("/api/health"), env.client.get("/api/alerts")):  # success and 401
        h = r.headers
        assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
        assert h["referrer-policy"] == "no-referrer" and "frame-ancestors 'none'" in h["content-security-policy"]
        assert h["cache-control"] == "no-store"
        assert "strict-transport-security" not in h  # only when ADAPTIVE_IDS_HSTS is set (HTTPS)
        assert "server" not in h


def test_web_app_csp(tmp_path, env):
    from fastapi.testclient import TestClient

    from adaptive_ids.api import create_app

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id=root></div>")
    settings = env.settings.__class__(**{**env.settings.__dict__, "web_dist_dir": dist, "hsts": True})
    with TestClient(create_app(settings)) as c:
        r = c.get("/alerts")
        csp = r.headers["content-security-policy"]
        assert r.status_code == 200 and "script-src 'self'" in csp and "unsafe-eval" not in csp
        assert r.headers["strict-transport-security"].startswith("max-age=")
        assert c.get("/../../etc/passwd").status_code in (200, 404)  # path traversal falls back to index, never a file
        assert "root:" not in c.get("/..%2F..%2Fetc%2Fpasswd").text


def test_oversized_json_bodies_are_refused(env):
    h = env.login("analyst", ANALYST_PW)
    big = "x" * (1024 * 1024 + 10)
    r = env.client.post("/api/incidents", headers={**h, "content-type": "application/json"}, content=f'{{"title": "{big}"}}')
    assert r.status_code == 413 and "too large" in r.json()["detail"]


def test_oversized_upload_is_refused_before_parsing(env):
    h = env.login("analyst", ANALYST_PW)
    payload = b"a,b\n" + b"1,2\n" * (env.settings.max_upload_mb * 1024 * 1024 // 4 + 100_000)
    r = env.client.post("/api/imports", headers=h, files={"file": ("big.csv", payload, "text/csv")},
                        data={"schema_id": "synthetic-flows-demo@1.1.0", "dataset_name": "big", "dataset_version": "1",
                              "provenance": "synthetic_demo"})
    assert r.status_code == 413


def test_validation_errors_never_echo_submitted_values(env):
    r = env.client.post("/api/auth/login", json={"username": "admin", "password": "p" * 300})
    assert r.status_code == 422 and "ppppp" not in r.text


def test_unexpected_errors_are_generic(env, monkeypatch):
    from adaptive_ids.services import dashboard

    def boom(*a, **k):
        raise RuntimeError("secret internal detail /srv/data/private.csv")

    monkeypatch.setattr(dashboard, "summary", boom)
    h = env.login("admin", ADMIN_PW)
    from fastapi.testclient import TestClient

    with TestClient(env.client.app, raise_server_exceptions=False) as c:
        r = c.get("/api/dashboard/summary", headers=h)
    assert r.status_code == 500 and r.json()["detail"] == "internal server error"
    assert "secret" not in r.text and "/srv" not in r.text and len(r.json()["reference"]) == 12


def test_csv_cells_neutralise_formulas():
    assert csv_cell("=HYPERLINK(\"http://x\")") == "'=HYPERLINK(\"http://x\")"
    assert csv_cell("@SUM(A1)") == "'@SUM(A1)" and csv_cell("+1") == "'+1" and csv_cell("\tcmd") == "'\tcmd"
    assert csv_cell(-0.25) == "-0.25" and csv_cell(3) == "3" and csv_cell(None) == "" and csv_cell("benign") == "benign"


def test_alert_export_escapes_untrusted_values(env):
    from adaptive_ids.db import session_scope
    from adaptive_ids.db.models import Alert
    from api_support import scored_import

    admin, analyst = env.login("admin", ADMIN_PW), env.login("analyst", ANALYST_PW)
    scored_import(env, admin, analyst)
    with session_scope(env.factory) as db:
        a = db.query(Alert).first()
        a.predicted_class = "=cmd|' /C calc'!A0"
    text = env.client.get("/api/alerts/export.csv", headers=analyst).text
    assert "'=cmd|" in text and ",=cmd|" not in text
