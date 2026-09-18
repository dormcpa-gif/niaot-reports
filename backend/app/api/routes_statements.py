from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.models import StatementORM, UserORM
from app.db.session import get_session
from app.mapping.classification import ClassifiedItem
from app.models.transactions import NormalizedStatement
from app.services.activity_log_service import log_activity
from app.services.extraction_service import extract_and_classify

router = APIRouter(prefix="/statements", tags=["statements"])


class StatementSummaryOut(BaseModel):
    id: str
    client_id: str
    tax_year: int
    broker: str
    original_filename: str
    dividend_count: int
    interest_count: int
    trade_count: int
    fee_count: int
    needs_review_count: int


class StatementDetailOut(BaseModel):
    id: str
    client_id: str
    tax_year: int
    broker: str
    statement: NormalizedStatement
    classified: list[ClassifiedItem]
    overrides: dict


def _summary_from_orm(orm: StatementORM) -> StatementSummaryOut:
    stmt = orm.normalized_statement_json
    needs_review = sum(1 for c in orm.classified_items_json if c.get("needs_review"))
    return StatementSummaryOut(
        id=orm.id,
        client_id=orm.client_id,
        tax_year=orm.tax_year,
        broker=orm.broker,
        original_filename=orm.original_filename,
        dividend_count=len(stmt.get("dividends", [])),
        interest_count=len(stmt.get("interest", [])),
        trade_count=len(stmt.get("trades", [])),
        fee_count=len(stmt.get("fees", [])),
        needs_review_count=needs_review,
    )


@router.get("/by-client/{client_id}", response_model=list[StatementSummaryOut])
def list_statements_for_client(client_id: str, session: Session = Depends(get_session)) -> list[StatementSummaryOut]:
    rows = (
        session.query(StatementORM)
        .filter(StatementORM.client_id == client_id)
        .order_by(StatementORM.uploaded_at.desc())
        .all()
    )
    return [_summary_from_orm(r) for r in rows]


@router.post("", response_model=StatementSummaryOut)
async def upload_statement(
    client_id: str = Form(...),
    tax_year: int = Form(...),
    broker: str = Form("IBKR"),
    file: UploadFile = File(...),
    user: UserORM = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> StatementSummaryOut:
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=422, detail="הקובץ שהועלה ריק.")
    statement_id = str(uuid.uuid4())
    try:
        result = extract_and_classify(file_bytes, statement_id, broker=broker)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:  # pdfplumber/pdfminer/csv raise various low-level errors on corrupt/wrong-format input
        raise HTTPException(
            status_code=422,
            detail=f"לא ניתן היה לפענח את הקובץ (שגיאה: {e}). ודאו שהקובץ אינו פגום ושהוא בפורמט הנכון לברוקר שנבחר.",
        ) from e

    orm = StatementORM(
        id=statement_id,
        client_id=client_id,
        tax_year=tax_year,
        broker=broker,
        original_filename=file.filename or "statement.pdf",
        normalized_statement_json=result.statement.model_dump(mode="json"),
        classified_items_json=[c.model_dump(mode="json") for c in result.classified],
        overrides_json={},
        fx_rates_json={},
        created_by_user_id=user.id,
    )
    session.add(orm)
    session.commit()
    log_activity(
        session,
        user,
        "statement.upload",
        target_type="statement",
        target_id=orm.id,
        detail={"client_id": client_id, "broker": broker, "tax_year": tax_year, "filename": orm.original_filename},
    )

    return _summary_from_orm(orm)


def _load(statement_id: str, session: Session) -> StatementORM:
    orm = session.get(StatementORM, statement_id)
    if orm is None:
        raise HTTPException(status_code=404, detail="Statement not found")
    return orm


@router.get("/{statement_id}", response_model=StatementDetailOut)
def get_statement(statement_id: str, session: Session = Depends(get_session)) -> StatementDetailOut:
    orm = _load(statement_id, session)
    return StatementDetailOut(
        id=orm.id,
        client_id=orm.client_id,
        tax_year=orm.tax_year,
        broker=orm.broker,
        statement=NormalizedStatement.model_validate(orm.normalized_statement_json),
        classified=[ClassifiedItem.model_validate(c) for c in orm.classified_items_json],
        overrides=orm.overrides_json or {},
    )


class OverridesIn(BaseModel):
    field_overrides: dict[str, str | None] = {}  # source_id -> new nispach_d_field (or null to clear)
    bracket_overrides: dict[str, str] = {}  # source_id (trade) -> "35"|"30"|"25"|"20"|"15"


@router.patch("/{statement_id}/overrides", response_model=StatementDetailOut)
def update_overrides(
    statement_id: str,
    payload: OverridesIn,
    user: UserORM = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> StatementDetailOut:
    orm = _load(statement_id, session)
    orm.overrides_json = payload.model_dump(mode="json")
    session.add(orm)
    session.commit()
    log_activity(session, user, "statement.overrides_update", target_type="statement", target_id=orm.id)
    return get_statement(statement_id, session)
