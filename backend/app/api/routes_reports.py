from __future__ import annotations

import io
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models import StatementORM
from app.db.session import get_session
from app.mapping.classification import ClassifiedItem
from app.models.transactions import Currency, NormalizedStatement
from app.output.excel_export import build_appendix_workbook
from app.services.currency_service import CurrencyService
from app.services.report_service import build_appendix_report

router = APIRouter(prefix="/statements", tags=["reports"])


class FxRateIn(BaseModel):
    currency: Currency = Currency.USD
    on_date: date
    rate: float


class ReportRequest(BaseModel):
    fx_rates: list[FxRateIn]


def _apply_overrides(classified: list[ClassifiedItem], overrides: dict) -> list[ClassifiedItem]:
    field_overrides: dict[str, str | None] = overrides.get("field_overrides", {})
    out: list[ClassifiedItem] = []
    for item in classified:
        if item.source_id in field_overrides:
            item = item.model_copy(update={"nispach_d_field": field_overrides[item.source_id], "needs_review": False})
        out.append(item)
    return out


@router.post("/{statement_id}/appendix.xlsx")
def generate_appendix_xlsx(statement_id: str, payload: ReportRequest, session: Session = Depends(get_session)) -> StreamingResponse:
    orm = session.get(StatementORM, statement_id)
    if orm is None:
        raise HTTPException(status_code=404, detail="Statement not found")
    if not payload.fx_rates:
        raise HTTPException(status_code=422, detail="At least one FX rate is required to convert USD amounts to ILS.")

    statement = NormalizedStatement.model_validate(orm.normalized_statement_json)
    classified = [ClassifiedItem.model_validate(c) for c in orm.classified_items_json]
    classified = _apply_overrides(classified, orm.overrides_json or {})

    dividends_by_id = {f"{d.symbol} {d.pay_date.isoformat()}": d for d in statement.dividends}

    rates = {(r.currency, r.on_date): r.rate for r in payload.fx_rates}
    currency_service = CurrencyService(rates)

    bracket_overrides = (orm.overrides_json or {}).get("bracket_overrides", {})

    try:
        report = build_appendix_report(statement, classified, dividends_by_id, currency_service, bracket_overrides)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    xlsx_bytes = build_appendix_workbook(report)
    filename = f"nespach_ezer_{statement_id[:8]}.xlsx"
    return StreamingResponse(
        io.BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
