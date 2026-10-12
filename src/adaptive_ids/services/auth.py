"""Users, login sessions and role checks."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import SessionToken, User, utcnow
from ..permissions import ROLES
from ..security import DUMMY_HASH, hash_password, hash_token, new_session_token, verify_password
from . import audit
from .errors import Conflict, InvalidRequest, NotAuthenticated, NotFound, PermissionDenied



def create_user(db: Session, username: str, password: str, role: str, *, actor: User | None = None) -> User:
    username = username.strip()
    if role not in ROLES:
        raise InvalidRequest(f"role must be one of {ROLES}")
    if not (3 <= len(username) <= 64) or not username.replace("_", "").replace("-", "").replace(".", "").isalnum():
        raise InvalidRequest("username must be 3-64 letters, digits, '.', '_' or '-'")
    if db.scalar(select(User).where(User.username == username)):
        raise Conflict("username already exists")
    try:
        pw = hash_password(password)
    except ValueError as exc:
        raise InvalidRequest(str(exc)) from exc
    user = User(username=username, password_hash=pw, role=role, is_active=True)
    db.add(user)
    db.flush()
    audit.record(db, "user.create", actor=actor, actor_name=None if actor else "cli",
                 entity_type="user", entity_id=user.id, details={"username": username, "role": role})
    return user


def login(db: Session, username: str, password: str, *, session_hours: int, client_ip: str | None) -> tuple[str, User]:
    user = db.scalar(select(User).where(User.username == username))
    ok = verify_password(password, user.password_hash if user else DUMMY_HASH)
    if not user or not ok or not user.is_active:
        audit.record(db, "auth.login_failed", actor_name=username[:64], client_ip=client_ip)
        raise NotAuthenticated("invalid username or password")
    token, token_hash = new_session_token()
    now = utcnow()
    db.add(SessionToken(user_id=user.id, token_hash=token_hash, expires_at=now + timedelta(hours=session_hours),
                        client_ip=client_ip))
    user.last_login_at = now
    audit.record(db, "auth.login", actor=user, client_ip=client_ip)
    return token, user


def authenticate(db: Session, token: str | None) -> User:
    if not token:
        raise NotAuthenticated("authentication required")
    sess = db.scalar(select(SessionToken).where(SessionToken.token_hash == hash_token(token)))
    if not sess or sess.revoked_at is not None or sess.expires_at <= utcnow() or not sess.user.is_active:
        raise NotAuthenticated("session is invalid or has expired")
    return sess.user


def logout(db: Session, token: str, user: User, client_ip: str | None) -> None:
    sess = db.scalar(select(SessionToken).where(SessionToken.token_hash == hash_token(token)))
    if sess and sess.revoked_at is None:
        sess.revoked_at = utcnow()
    audit.record(db, "auth.logout", actor=user, client_ip=client_ip)


def set_active(db: Session, user_id: int, active: bool, *, actor: User) -> User:
    user = db.get(User, user_id)
    if not user:
        raise NotFound("user not found")
    if user.id == actor.id and not active:
        raise InvalidRequest("you cannot deactivate your own account")
    user.is_active = active
    if not active:  # revoke live sessions
        for s in db.scalars(select(SessionToken).where(SessionToken.user_id == user.id, SessionToken.revoked_at.is_(None))):
            s.revoked_at = utcnow()
    audit.record(db, "user.activate" if active else "user.deactivate", actor=actor, entity_type="user", entity_id=user.id)
    return user
