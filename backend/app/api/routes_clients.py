from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.models import ClientORM, UserORM
from app.db.session import get_session
from app.services.activity_log_service import log_activity

router = APIRouter(prefix="/clients", tags=["clients"])


class ClientIn(BaseModel):
    full_name: str
    tax_file_number: str | None = None


class ClientOut(BaseModel):
    id: str
    full_name: str
    tax_file_number: str | None
    created_by_name: str | None = None


def _client_out(client: ClientORM, creator_name: str | None) -> ClientOut:
    return ClientOut(
        id=client.id,
        full_name=client.full_name,
        tax_file_number=client.tax_file_number,
        created_by_name=creator_name,
    )


@router.get("", response_model=list[ClientOut])
def list_clients(session: Session = Depends(get_session)) -> list[ClientOut]:
    clients = session.query(ClientORM).order_by(ClientORM.full_name).all()
    creator_ids = {c.created_by_user_id for c in clients if c.created_by_user_id}
    names_by_id = {u.id: u.full_name for u in session.query(UserORM).filter(UserORM.id.in_(creator_ids)).all()}
    return [_client_out(c, names_by_id.get(c.created_by_user_id)) for c in clients]


@router.post("", response_model=ClientOut)
def create_client(
    payload: ClientIn,
    user: UserORM = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> ClientOut:
    client = ClientORM(full_name=payload.full_name, tax_file_number=payload.tax_file_number, created_by_user_id=user.id)
    session.add(client)
    session.commit()
    session.refresh(client)
    log_activity(session, user, "client.create", target_type="client", target_id=client.id, detail={"full_name": client.full_name})
    return _client_out(client, user.full_name)
