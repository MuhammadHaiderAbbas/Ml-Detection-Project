"""Users, login sessions, login throttling and account administration.

Login throttling counts recent ``auth.login_failed`` audit records, so it survives
restarts and works across several server processes: after ``login_max_failures``
failures for one username (or ``login_ip_max_failures`` from one address) within
``login_window_minutes``, further attempts get HTTP 429 until the window passes.
A successful login does not reset another address's counter.

Sessions expire after ``session_hours`` and after ``session_idle_minutes`` without
use. Changing a password, resetting it, changing a role or deactivating a user
revokes that user's sessions.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import AuditLog, SessionToken, User, utcnow
from ..permissions import ROLES
from ..security import DUMMY_HASH, check_password_policy, hash_password, hash_token, new_session_token, verify_password
from . import audit
from .errors import Conflict, InvalidRequest, NotAuthenticated, NotFound, TooManyRequests



def create_user(db: Session, username: str, password: str, role: str, *, actor: User | None = None) -> User:
    username = username.strip()
    if role not in ROLES:
        raise InvalidRequest(f"role must be one of {ROLES}")
    if not (3 <= len(username) <= 64) or not username.replace("_", "").replace("-", "").replace(".", "").isalnum():
        raise InvalidRequest("username must be 3-64 letters, digits, '.', '_' or '-'")
    if db.scalar(select(User).where(User.username == username)):
        raise Conflict("username already exists")
    try:
        check_password_policy(password, username)
        pw = hash_password(password)
    except ValueError as exc:
        raise InvalidRequest(str(exc)) from exc
    user = User(username=username, password_hash=pw, role=role, is_active=True)
    db.add(user)
    db.flush()
    audit.record(db, "user.create", actor=actor, actor_name=None if actor else "cli",
                 entity_type="user", entity_id=user.id, details={"username": username, "role": role})
    return user


def _recent_failures(db: Session, since, *, username: str | None = None, client_ip: str | None = None) -> int:
    q = select(func.count(AuditLog.id)).where(AuditLog.action == "auth.login_failed", AuditLog.at >= since)
    if username is not None:
        q = q.where(AuditLog.actor_name == username[:64])
    if client_ip is not None:
        q = q.where(AuditLog.client_ip == client_ip)
    return db.scalar(q) or 0


def login(db: Session, username: str, password: str, *, session_hours: int, client_ip: str | None,
          max_failures: int = 5, ip_max_failures: int = 20, window_minutes: int = 15) -> tuple[str, User]:
    now = utcnow()
    since = now - timedelta(minutes=window_minutes)
    if (_recent_failures(db, since, username=username) >= max_failures
            or (client_ip and _recent_failures(db, since, client_ip=client_ip) >= ip_max_failures)):
        audit.record(db, "auth.login_throttled", actor_name=username[:64], client_ip=client_ip)
        raise TooManyRequests("too many failed sign-in attempts; try again later", retry_after_s=window_minutes * 60)
    user = db.scalar(select(User).where(User.username == username))
    ok = verify_password(password, user.password_hash if user else DUMMY_HASH)
    if not user or not ok or not user.is_active:
        audit.record(db, "auth.login_failed", actor_name=username[:64], client_ip=client_ip)
        raise NotAuthenticated("invalid username or password")
    token, token_hash = new_session_token()
    db.add(SessionToken(user_id=user.id, token_hash=token_hash, expires_at=now + timedelta(hours=session_hours),
                        last_seen_at=now, client_ip=client_ip))
    user.last_login_at = now
    audit.record(db, "auth.login", actor=user, client_ip=client_ip)
    return token, user


def authenticate(db: Session, token: str | None, *, idle_minutes: int | None = None) -> User:
    if not token:
        raise NotAuthenticated("authentication required")
    sess = db.scalar(select(SessionToken).where(SessionToken.token_hash == hash_token(token)))
    now = utcnow()
    if not sess or sess.revoked_at is not None or sess.expires_at <= now or not sess.user.is_active:
        raise NotAuthenticated("session is invalid or has expired")
    if idle_minutes and sess.last_seen_at and now - sess.last_seen_at > timedelta(minutes=idle_minutes):
        sess.revoked_at = now
        db.commit()  # persist the revocation even though this request fails
        raise NotAuthenticated("session expired after inactivity; sign in again")
    if sess.last_seen_at is None or now - sess.last_seen_at > timedelta(minutes=1):
        sess.last_seen_at = now
    return sess.user


def _revoke_sessions(db: Session, user_id: int, *, keep_token_hash: str | None = None) -> int:
    n = 0
    for s in db.scalars(select(SessionToken).where(SessionToken.user_id == user_id, SessionToken.revoked_at.is_(None))):
        if s.token_hash != keep_token_hash:
            s.revoked_at = utcnow()
            n += 1
    return n


def _active_admins(db: Session) -> int:
    return db.scalar(select(func.count(User.id)).where(User.role == "admin", User.is_active.is_(True))) or 0


def change_password(db: Session, user: User, current: str, new: str, *, token: str, client_ip: str | None) -> None:
    """The signed-in user changes their own password; their other sessions are signed out."""
    if not verify_password(current, user.password_hash):
        audit.record(db, "auth.password_change_failed", actor=user, client_ip=client_ip)
        db.commit()
        raise InvalidRequest("current password is incorrect")
    if verify_password(new, user.password_hash):
        raise InvalidRequest("the new password must differ from the current one")
    try:
        check_password_policy(new, user.username)
    except ValueError as exc:
        raise InvalidRequest(str(exc)) from exc
    user.password_hash = hash_password(new)
    revoked = _revoke_sessions(db, user.id, keep_token_hash=hash_token(token))
    audit.record(db, "auth.password_change", actor=user, entity_type="user", entity_id=user.id,
                 details={"other_sessions_revoked": revoked}, client_ip=client_ip)


def update_user(db: Session, user_id: int, *, actor: User, is_active: bool | None = None, role: str | None = None,
                password: str | None = None, client_ip: str | None = None) -> User:
    """Admin changes to another account. Every change revokes that user's sessions except a reactivation."""
    user = db.get(User, user_id)
    if not user:
        raise NotFound("user not found")
    if is_active is None and role is None and password is None:
        raise InvalidRequest("nothing to change")
    if user.id == actor.id and (is_active is False or (role is not None and role != user.role)):
        raise InvalidRequest("you cannot deactivate or change the role of your own account")
    if role is not None and role not in ROLES:
        raise InvalidRequest(f"role must be one of {ROLES}")
    removes_admin = user.role == "admin" and user.is_active and (is_active is False or (role is not None and role != "admin"))
    if removes_admin and _active_admins(db) <= 1:
        raise Conflict("this is the last active administrator; promote another admin first")
    changes: dict[str, object] = {}
    if is_active is not None and is_active != user.is_active:
        user.is_active = is_active
        changes["is_active"] = is_active
        audit.record(db, "user.activate" if is_active else "user.deactivate", actor=actor, entity_type="user",
                     entity_id=user.id, client_ip=client_ip)
    if role is not None and role != user.role:
        audit.record(db, "user.role_change", actor=actor, entity_type="user", entity_id=user.id,
                     details={"from": user.role, "to": role}, client_ip=client_ip)
        user.role = role
        changes["role"] = role
    if password is not None:
        try:
            check_password_policy(password, user.username)
        except ValueError as exc:
            raise InvalidRequest(str(exc)) from exc
        user.password_hash = hash_password(password)
        changes["password_reset"] = True
        audit.record(db, "user.password_reset", actor=actor, entity_type="user", entity_id=user.id, client_ip=client_ip)
    if changes.get("is_active") is False or "role" in changes or "password_reset" in changes:
        _revoke_sessions(db, user.id)
    return user


def logout(db: Session, token: str, user: User, client_ip: str | None) -> None:
    sess = db.scalar(select(SessionToken).where(SessionToken.token_hash == hash_token(token)))
    if sess and sess.revoked_at is None:
        sess.revoked_at = utcnow()
    audit.record(db, "auth.logout", actor=user, client_ip=client_ip)

