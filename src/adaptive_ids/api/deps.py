"""FastAPI dependencies: database session, current user, role checks."""

from __future__ import annotations

from collections.abc import Callable, Iterator

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from ..db.models import User
from ..services import auth as auth_svc
from ..services.errors import NotAuthenticated


def get_db(request: Request) -> Iterator[Session]:
    db = request.app.state.session_factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = bearer_token(request)
    if token is None:
        raise NotAuthenticated("authentication required")
    return auth_svc.authenticate(db, token)


def require(*roles: str) -> Callable[..., User]:
    def dep(user: User = Depends(current_user)) -> User:
        auth_svc.require_role(user, *roles)
        return user

    return dep


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None
