"""Per-user authentication: bcrypt password hashing, opaque bearer-token
sessions stored in the DB (not JWT -- revocation/expiry is then just a row
delete/update, with no signing-key rotation story to get wrong), and role
checks. Replaces the earlier single-shared-password gate entirely.

First admin account: bootstrap_admin_if_needed() creates one user from
ADMIN_EMAIL/ADMIN_PASSWORD env vars if the users table is still empty --
see main.py's startup hook. From then on, admins create every other
account through the /admin/users routes.
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta

import bcrypt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.db.models import SessionORM, UserORM
from app.db.session import get_session

_SESSION_TTL = timedelta(days=7)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # malformed/legacy hash -- treat as a mismatch, not a crash
        return False


def create_session(db: Session, user: UserORM) -> str:
    token = secrets.token_urlsafe(32)
    db.add(
        SessionORM(
            token=token,
            user_id=user.id,
            expires_at=datetime.utcnow() + _SESSION_TTL,
        )
    )
    db.commit()
    return token


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="נדרשת כניסה למערכת (חסר Authorization header)")
    return authorization[len("bearer ") :].strip()


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_session),
) -> UserORM:
    token = _extract_bearer_token(authorization)
    session_row = db.get(SessionORM, token)
    if session_row is None or session_row.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="החיבור פג תוקף - יש להתחבר מחדש")

    user = db.get(UserORM, session_row.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="המשתמש אינו פעיל")

    # sliding expiry: every authenticated request extends the session
    session_row.expires_at = datetime.utcnow() + _SESSION_TTL
    db.add(session_row)
    db.commit()

    return user


def require_admin(user: UserORM = Depends(get_current_user)) -> UserORM:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="פעולה זו מוגבלת למנהלי מערכת")
    return user


def bootstrap_admin_if_needed(db: Session) -> None:
    if db.query(UserORM).first() is not None:
        return
    email = os.environ.get("ADMIN_EMAIL")
    password = os.environ.get("ADMIN_PASSWORD")
    if not email or not password:
        return
    db.add(
        UserORM(
            email=email,
            password_hash=hash_password(password),
            full_name="מנהל מערכת",
            role="admin",
        )
    )
    db.commit()
