"""Phase 7: every route is covered by an explicit permission, and roles are enforced server-side."""

from __future__ import annotations

import re

import pytest
from api_support import ADMIN_PW, ANALYST_PW, VIEWER_PW, demo_runs, env, upload  # noqa: F401

from adaptive_ids.api import create_app, deps
from adaptive_ids.permissions import PERMISSIONS, ROLES, allowed, permissions_for
from adaptive_ids.settings import Settings

PUBLIC = {("GET", "/api/health"), ("POST", "/api/auth/login")}
AUTH_ONLY = {("POST", "/api/auth/logout"), ("GET", "/api/auth/me"), ("POST", "/api/auth/password")}
WRITE_SUFFIXES = (".write", ".import", ".run", ".export", ".manage")


def _routes():
    app = create_app(Settings(database_url="sqlite://"))
    out = []

    def walk(d, acc):
        if getattr(d.call, "permission", None):
            acc.append(d.call.permission)
        if d.call is deps.current_user:
            acc.append("<auth>")
        for s in d.dependencies:
            walk(s, acc)

    for r in app.routes:
        if not hasattr(r, "dependant"):
            continue
        acc: list[str] = []
        walk(r.dependant, acc)
        for m in r.methods - {"HEAD"}:
            out.append((m, r.path, [a for a in acc if a != "<auth>"], "<auth>" in acc))
    return out


ROUTES = _routes()


def test_every_route_declares_exactly_one_permission():
    for method, path, perms, authed in ROUTES:
        key = (method, path)
        if key in PUBLIC:
            assert not authed and not perms, key
        elif key in AUTH_ONLY:
            assert authed and not perms, key
        else:
            assert len(perms) == 1, f"{method} {path} must declare exactly one permission, has {perms}"
            assert perms[0] in PERMISSIONS


def test_state_changing_routes_never_use_read_permissions():
    for method, path, perms, _ in ROUTES:
        if method != "GET" and perms:
            assert perms[0].endswith(WRITE_SUFFIXES), f"{method} {path} uses {perms[0]}"


def test_role_matrix():
    assert ROLES == ("admin", "analyst", "viewer")
    assert set(permissions_for("admin")) == set(PERMISSIONS)
    assert not [p for p in permissions_for("viewer") if p.endswith(WRITE_SUFFIXES)]
    assert not [p for p in permissions_for("analyst") if p.endswith(".manage")] and not allowed("analyst", "audit.read")
    with pytest.raises(KeyError):
        allowed("admin", "no.such.permission")


def _call(env, method, path, headers):
    url = re.sub(r"\{[^}]+\}", "1", path)
    return env.client.request(method, url, headers=headers, json={})


def test_unauthenticated_requests_are_rejected_everywhere(env):
    for method, path, _, _ in ROUTES:
        if (method, path) in PUBLIC:
            continue
        r = _call(env, method, path, {})
        assert r.status_code == 401, (method, path, r.status_code)
        assert r.headers.get("www-authenticate") == "Bearer"


@pytest.mark.parametrize("role,password", [("viewer", VIEWER_PW), ("analyst", ANALYST_PW)])
def test_roles_are_refused_everything_their_permissions_do_not_grant(env, role, password):
    h = env.login(role, password)
    checked = 0
    for method, path, perms, _ in ROUTES:
        if not perms or allowed(role, perms[0]):
            continue
        r = _call(env, method, path, h)
        assert r.status_code == 403, (role, method, path, r.status_code, r.text)
        assert role in r.json()["detail"] and perms[0] in r.json()["detail"]
        checked += 1
    assert checked >= (25 if role == "viewer" else 9)  # analyst: models.manage (6), users.manage (2), audit.read


def test_viewer_can_read(env):
    h = env.login("viewer", VIEWER_PW)
    me = env.client.get("/api/auth/me", headers=h).json()
    assert me["role"] == "viewer" and "alerts.read" in me["permissions"] and "alerts.write" not in me["permissions"]
    for path in ("/api/dashboard/summary", "/api/alerts", "/api/incidents", "/api/models", "/api/drift/analyses",
                 "/api/imports", "/api/users", "/api/governance/protocol"):
        assert env.client.get(path, headers=h).status_code == 200, path
    assert env.client.get("/api/alerts/export.csv", headers=h).status_code == 403
    assert env.client.get("/api/audit-logs", headers=h).status_code == 403


def test_login_response_carries_permissions(env):
    r = env.client.post("/api/auth/login", json={"username": "analyst", "password": ANALYST_PW})
    perms = r.json()["user"]["permissions"]
    assert "data.import" in perms and "models.manage" not in perms


def test_only_the_importer_or_an_admin_can_cancel(env, tmp_path):
    from adaptive_ids.db import session_scope
    from adaptive_ids.db.models import DatasetImport

    analyst, admin = env.login("analyst", ANALYST_PW), env.login("admin", ADMIN_PW)
    imp = upload(env, admin).json()["id"]
    with session_scope(env.factory) as db:  # pretend it is still running
        db.get(DatasetImport, imp).status = "running"
    r = env.client.post(f"/api/imports/{imp}/cancel", headers=analyst)
    assert r.status_code == 403 and "started an import" in r.json()["detail"]
    assert env.client.post(f"/api/imports/{imp}/cancel", headers=admin).status_code == 200


def test_admin_can_create_a_viewer(env):
    admin = env.login("admin", ADMIN_PW)
    r = env.client.post("/api/users", json={"username": "auditor", "password": "auditor-password-1", "role": "viewer"}, headers=admin)
    assert r.status_code == 201 and r.json()["role"] == "viewer"
    assert env.client.post("/api/users", json={"username": "x-root", "password": "auditor-password-1", "role": "root"},
                           headers=admin).status_code == 422
