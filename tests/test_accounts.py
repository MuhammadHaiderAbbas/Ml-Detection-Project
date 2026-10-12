"""Phase 7: login throttling, idle sessions, password changes and account administration."""

from __future__ import annotations

from datetime import timedelta

import pytest
from api_support import ADMIN_PW, ANALYST_PW, demo_runs, env  # noqa: F401
from sqlalchemy import select

from adaptive_ids.db import session_scope
from adaptive_ids.db.models import AuditLog, SessionToken, User, utcnow
from adaptive_ids.security import check_password_policy


def _login(env, user, pw):
    return env.client.post("/api/auth/login", json={"username": user, "password": pw})


def _actions(env, action):
    with session_scope(env.factory) as db:
        return list(db.scalars(select(AuditLog).where(AuditLog.action == action)))


@pytest.mark.parametrize("pw,reason", [("short", "at least"), ("aaaaaaaaaaaaaaab", "repetitive"),
                                       ("Password1234", "common"), ("my-alice-secret-99", "username")])
def test_password_policy(pw, reason):
    with pytest.raises(ValueError, match=reason):
        check_password_policy(pw, "alice")
    check_password_policy("correct-horse-battery-9", "alice")


def test_username_lockout_after_repeated_failures(env):
    for _ in range(5):
        assert _login(env, "analyst", "not-the-password").status_code == 401
    r = _login(env, "analyst", ANALYST_PW)  # even the right password is refused while locked
    assert r.status_code == 429 and int(r.headers["retry-after"]) == 15 * 60
    assert "too many" in r.json()["detail"]
    assert _login(env, "admin", ADMIN_PW).status_code == 200  # other accounts are unaffected
    assert len(_actions(env, "auth.login_throttled")) == 1
    # the window passes
    with session_scope(env.factory) as db:
        for a in db.scalars(select(AuditLog).where(AuditLog.action == "auth.login_failed")):
            a.at = utcnow() - timedelta(minutes=16)
    assert _login(env, "analyst", ANALYST_PW).status_code == 200


def test_address_throttle_across_usernames(env):
    object.__setattr__(env.client.app.state.settings, "login_ip_max_failures", 3)
    for name in ("nobody1", "nobody2", "nobody3"):
        assert _login(env, name, "whatever-password").status_code == 401
    assert _login(env, "admin", ADMIN_PW).status_code == 429


def test_idle_sessions_expire(env):
    h = env.login("analyst", ANALYST_PW)
    assert env.client.get("/api/auth/me", headers=h).status_code == 200
    with session_scope(env.factory) as db:
        for s in db.scalars(select(SessionToken)):
            s.last_seen_at = utcnow() - timedelta(minutes=61)
    r = env.client.get("/api/auth/me", headers=h)
    assert r.status_code == 401 and "inactivity" in r.json()["detail"]
    assert env.client.get("/api/auth/me", headers=h).status_code == 401  # revoked, not just refused once


def test_change_own_password(env):
    h1, h2 = env.login("analyst", ANALYST_PW), env.login("analyst", ANALYST_PW)
    url = "/api/auth/password"
    assert env.client.post(url, json={"current_password": "wrong-password-1", "new_password": "new-river-stone-55"},
                           headers=h1).status_code == 400
    assert env.client.post(url, json={"current_password": ANALYST_PW, "new_password": ANALYST_PW}, headers=h1).status_code == 400
    r = env.client.post(url, json={"current_password": ANALYST_PW, "new_password": "the-analyst-pass-99"}, headers=h1)
    assert r.status_code == 400 and "username" in r.json()["detail"]
    assert env.client.post(url, json={"current_password": ANALYST_PW, "new_password": "new-river-stone-55"},
                           headers=h1).status_code == 204
    assert env.client.get("/api/auth/me", headers=h1).status_code == 200  # this session stays
    assert env.client.get("/api/auth/me", headers=h2).status_code == 401  # the other one is signed out
    assert _login(env, "analyst", ANALYST_PW).status_code == 401
    assert _login(env, "analyst", "new-river-stone-55").status_code == 200
    assert len(_actions(env, "auth.password_change")) == 1 and len(_actions(env, "auth.password_change_failed")) == 1


def test_admin_role_change_and_password_reset_sign_the_user_out(env):
    admin, analyst = env.login("admin", ADMIN_PW), env.login("analyst", ANALYST_PW)
    with session_scope(env.factory) as db:
        uid = db.scalar(select(User.id).where(User.username == "analyst"))
    r = env.client.patch(f"/api/users/{uid}", json={"role": "viewer"}, headers=admin)
    assert r.status_code == 200 and r.json()["role"] == "viewer"
    assert env.client.get("/api/auth/me", headers=analyst).status_code == 401
    assert _actions(env, "user.role_change")[0].details == {"from": "analyst", "to": "viewer"}
    assert env.client.patch(f"/api/users/{uid}", json={"password": "short"}, headers=admin).status_code == 422
    assert env.client.patch(f"/api/users/{uid}", json={"password": "Password1234"}, headers=admin).status_code == 400
    assert env.client.patch(f"/api/users/{uid}", json={"password": "fresh-copper-kite-31"}, headers=admin).status_code == 200
    me = env.client.post("/api/auth/login", json={"username": "analyst", "password": "fresh-copper-kite-31"}).json()["user"]
    assert me["role"] == "viewer" and "alerts.write" not in me["permissions"]
    assert env.client.patch(f"/api/users/{uid}", json={}, headers=admin).status_code == 400


def test_admins_cannot_lock_themselves_out(env):
    admin = env.login("admin", ADMIN_PW)
    with session_scope(env.factory) as db:
        me = db.scalar(select(User.id).where(User.username == "admin"))
    for body in ({"is_active": False}, {"role": "analyst"}):
        r = env.client.patch(f"/api/users/{me}", json=body, headers=admin)
        assert r.status_code == 400 and "your own account" in r.json()["detail"]


def test_last_admin_guard(env):
    from adaptive_ids.services import auth
    from adaptive_ids.services.errors import Conflict

    with session_scope(env.factory) as db:
        a = db.scalar(select(User).where(User.username == "admin"))
        b = auth.create_user(db, "second-admin", "orbit-lantern-cedar-8", "admin")
        auth.update_user(db, a.id, actor=b, role="analyst")  # fine: b is still an admin
        a.role = "admin"  # a acts while b is the only other admin, then b tries to demote a concurrently
        b.is_active = False
        with pytest.raises(Conflict, match="last active administrator"):
            auth.update_user(db, a.id, actor=b, is_active=False)


def test_login_does_not_leak_whether_a_user_exists(env):
    unknown = _login(env, "no-such-user", "some-password-1")
    known = _login(env, "analyst", "some-password-1")
    assert unknown.status_code == known.status_code == 401 and unknown.json() == known.json()
