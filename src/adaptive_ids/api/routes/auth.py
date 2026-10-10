from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.models import User
from ...services import auth as svc
from ...services.errors import NotAuthenticated
from ..deps import bearer_token, client_ip, current_user, get_db, require
from ..schemas import LoginRequest, LoginResponse, UserActive, UserCreate, UserOut

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    settings = request.app.state.settings
    try:
        token, user = svc.login(db, body.username, body.password, session_hours=settings.session_hours,
                                client_ip=client_ip(request))
    except NotAuthenticated:
        db.commit()  # keep the failed-login audit record
        raise
    return LoginResponse(access_token=token, expires_in_hours=settings.session_hours, user=UserOut.model_validate(user))


@router.post("/auth/logout", status_code=204)
def logout(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    svc.logout(db, bearer_token(request) or "", user, client_ip(request))


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


@router.get("/users", response_model=list[UserOut])
def list_users(_: User = Depends(current_user), db: Session = Depends(get_db)):
    return list(db.scalars(select(User).order_by(User.username)))


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, request: Request, admin: User = Depends(require("admin")), db: Session = Depends(get_db)):
    return svc.create_user(db, body.username, body.password, body.role, actor=admin)


@router.patch("/users/{user_id}", response_model=UserOut)
def set_active(user_id: int, body: UserActive, request: Request, admin: User = Depends(require("admin")),
               db: Session = Depends(get_db)):
    return svc.set_active(db, user_id, body.is_active, actor=admin)
