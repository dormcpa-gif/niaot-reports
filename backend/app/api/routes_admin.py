from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import hash_password, require_admin
from app.db.models import ActivityLogORM, UserORM
from app.db.session import get_session
from app.services.activity_log_service import log_activity

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


class UserAdminOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


def _user_out(u: UserORM) -> UserAdminOut:
    return UserAdminOut(
        id=u.id,
        email=u.email,
        full_name=u.full_name,
        role=u.role,
        is_active=u.is_active,
        created_at=u.created_at,
        last_login_at=u.last_login_at,
    )


@router.get("/users", response_model=list[UserAdminOut])
def list_users(db: Session = Depends(get_session)) -> list[UserAdminOut]:
    return [_user_out(u) for u in db.query(UserORM).order_by(UserORM.created_at).all()]


class CreateUserIn(BaseModel):
    full_name: str
    email: str
    password: str
    role: str = "employee"


@router.post("/users", response_model=UserAdminOut)
def create_user(
    payload: CreateUserIn, admin: UserORM = Depends(require_admin), db: Session = Depends(get_session)
) -> UserAdminOut:
    if payload.role not in ("admin", "employee"):
        raise HTTPException(status_code=422, detail="תפקיד לא תקין (admin/employee בלבד)")
    if db.query(UserORM).filter(UserORM.email == payload.email).first() is not None:
        raise HTTPException(status_code=409, detail="כבר קיים משתמש עם אימייל זה")

    user = UserORM(
        full_name=payload.full_name,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    db.commit()
    log_activity(db, admin, "user.create", target_type="user", target_id=user.id, detail={"email": user.email})
    return _user_out(user)


class UpdateUserIn(BaseModel):
    role: str | None = None
    is_active: bool | None = None


@router.patch("/users/{user_id}", response_model=UserAdminOut)
def update_user(
    user_id: str,
    payload: UpdateUserIn,
    admin: UserORM = Depends(require_admin),
    db: Session = Depends(get_session),
) -> UserAdminOut:
    user = db.get(UserORM, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if payload.role is not None:
        if payload.role not in ("admin", "employee"):
            raise HTTPException(status_code=422, detail="תפקיד לא תקין (admin/employee בלבד)")
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
    db.add(user)
    db.commit()
    log_activity(
        db, admin, "user.update", target_type="user", target_id=user.id, detail=payload.model_dump(exclude_none=True)
    )
    return _user_out(user)


class ResetPasswordIn(BaseModel):
    new_password: str


@router.post("/users/{user_id}/reset-password")
def reset_password(
    user_id: str,
    payload: ResetPasswordIn,
    admin: UserORM = Depends(require_admin),
    db: Session = Depends(get_session),
) -> dict[str, bool]:
    user = db.get(UserORM, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    user.password_hash = hash_password(payload.new_password)
    db.add(user)
    db.commit()
    log_activity(db, admin, "user.password_reset", target_type="user", target_id=user.id)
    return {"ok": True}


class ActivityLogRowOut(BaseModel):
    id: str
    user_id: str | None
    user_email: str | None
    action: str
    target_type: str | None
    target_id: str | None
    detail: dict[str, Any] | None
    created_at: datetime


@router.get("/activity", response_model=list[ActivityLogRowOut])
def get_activity(
    user_id: str | None = None,
    action: str | None = None,
    limit: int = 200,
    offset: int = 0,
    db: Session = Depends(get_session),
) -> list[ActivityLogRowOut]:
    query = db.query(ActivityLogORM)
    if user_id:
        query = query.filter(ActivityLogORM.user_id == user_id)
    if action:
        query = query.filter(ActivityLogORM.action == action)
    rows = query.order_by(ActivityLogORM.created_at.desc()).offset(offset).limit(min(limit, 500)).all()

    user_ids = {r.user_id for r in rows if r.user_id}
    users_by_id = {u.id: u for u in db.query(UserORM).filter(UserORM.id.in_(user_ids)).all()} if user_ids else {}

    return [
        ActivityLogRowOut(
            id=r.id,
            user_id=r.user_id,
            user_email=users_by_id[r.user_id].email if r.user_id in users_by_id else None,
            action=r.action,
            target_type=r.target_type,
            target_id=r.target_id,
            detail=r.detail,
            created_at=r.created_at,
        )
        for r in rows
    ]
