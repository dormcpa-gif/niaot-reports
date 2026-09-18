"""Records who did what, when -- for the admin's oversight/troubleshooting
view (routes_admin.py's GET /admin/activity). One small helper called
from the existing route handlers at their key mutation points, rather
than a generic middleware that would log every request indiscriminately
(including read-only polling) and drown the signal."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import ActivityLogORM, UserORM


def log_activity(
    db: Session,
    user: UserORM | None,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    db.add(
        ActivityLogORM(
            user_id=user.id if user else None,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
        )
    )
    db.commit()
