from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models import ClientORM
from app.db.session import get_session

router = APIRouter(prefix="/clients", tags=["clients"])


class ClientIn(BaseModel):
    full_name: str
    tax_file_number: str | None = None


class ClientOut(BaseModel):
    id: str
    full_name: str
    tax_file_number: str | None

    model_config = {"from_attributes": True}


@router.get("", response_model=list[ClientOut])
def list_clients(session: Session = Depends(get_session)) -> list[ClientORM]:
    return session.query(ClientORM).order_by(ClientORM.full_name).all()


@router.post("", response_model=ClientOut)
def create_client(payload: ClientIn, session: Session = Depends(get_session)) -> ClientORM:
    client = ClientORM(full_name=payload.full_name, tax_file_number=payload.tax_file_number)
    session.add(client)
    session.commit()
    session.refresh(client)
    return client
