from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.models import User
from ...services import auth as svc
from ...services.errors import NotAuthenticated, TooManyRequests
from ..deps import allow, bearer_token, client_ip, current_user, get_db
from ..schemas import LoginRequest, LoginResponse, MeOut, PasswordChange, UserCreate, UserOut, UserUpdate

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    settings = request.app.state.settings
    try:
        token, user = svc.login(db, body.username, body.password, session_hours=settings.session_hours,
                                client_ip=client_ip(request), max_failures=settings.login_max_failures,
                                ip_max_failures=settings.login_ip_max_failures,
                                window_minutes=settings.login_window_minutes)
    except (NotAuthenticated, TooManyRequests):
        db.commit()  # keep the failed or throttled login audit record
        raise
    return LoginResponse(access_token=token, expires_in_hours=settings.session_hours, user=MeOut.of(user))


@router.post("/auth/logout", status_code=204)
def logout(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    svc.logout(db, bearer_token(request) or "", user, client_ip(request))


@router.post("/auth/password", status_code=204)
def change_password(body: PasswordChange, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Change your own password. Your other sessions are signed out; this one stays."""
    svc.change_password(db, user, body.current_password, body.new_password, token=bearer_token(request) or "",
                        client_ip=client_ip(request))


@router.get("/auth/me", response_model=MeOut)
def me(user: User = Depends(current_user)):
    return MeOut.of(user)


@router.get("/users", response_model=list[UserOut])
def list_users(_: User = Depends(allow("users.read")), db: Session = Depends(get_db)):
    return list(db.scalars(select(User).order_by(User.username)))


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, request: Request, admin: User = Depends(allow("users.manage")), db: Session = Depends(get_db)):
    return svc.create_user(db, body.username, body.password, body.role, actor=admin)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, request: Request, admin: User = Depends(allow("users.manage")),
                db: Session = Depends(get_db)):
    """Activate/deactivate, change role or reset password. Changes sign the user out everywhere."""
    return svc.update_user(db, user_id, actor=admin, is_active=body.is_active, role=body.role, password=body.password,
                           client_ip=client_ip(request))
