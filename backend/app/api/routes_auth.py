from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import create_session, get_current_user, verify_password
from app.db.models import SessionORM, UserORM
from app.db.session import get_session
from app.services.activity_log_service import log_activity

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: str


class LoginOut(BaseModel):
    token: str
    user: UserOut


@router.post("/login", response_model=LoginOut)
def login(payload: LoginIn, db: Session = Depends(get_session)) -> LoginOut:
    user = db.query(UserORM).filter(UserORM.email == payload.email).first()
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        log_activity(db, None, "login_failed", target_type="user", detail={"email": payload.email})
        raise HTTPException(status_code=401, detail="אימייל או סיסמה שגויים")

    token = create_session(db, user)
    user.last_login_at = datetime.utcnow()
    db.add(user)
    db.commit()
    log_activity(db, user, "login", target_type="user", target_id=user.id)

    return LoginOut(token=token, user=UserOut(id=user.id, email=user.email, full_name=user.full_name, role=user.role))


@router.post("/logout")
def logout(authorization: str | None = Header(default=None), db: Session = Depends(get_session)) -> dict[str, bool]:
    # get_current_user already validated the token if present; re-derive
    # it here only to know which row to delete (logout of an
    # already-invalid token is a harmless no-op, not an error).
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[len("bearer ") :].strip()
        session_row = db.get(SessionORM, token)
        if session_row is not None:
            db.delete(session_row)
            db.commit()
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: UserORM = Depends(get_current_user)) -> UserOut:
    return UserOut(id=user.id, email=user.email, full_name=user.full_name, role=user.role)
