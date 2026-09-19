from __future__ import annotations

import io
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.models import StatementORM, UserORM
from app.db.session import get_session
from app.mapping.classification import ClassifiedItem
from app.models.transactions import Currency, NormalizedStatement
from app.output.excel_export import build_appendix_workbook
from app.services.activity_log_service import log_activity
from app.services.boi_rates import BoiRatesUnavailable, fetch_rates_covering
from app.services.currency_service import CurrencyService
from app.services.report_service import build_appendix_report

router = APIRouter(prefix="/statements", tags=["reports"])


class FxRateIn(BaseModel):
    currency: Currency = Currency.USD
    on_date: date
    rate: float


class ReportRequest(BaseModel):
    fx_rates: list[FxRateIn] = []
    # None = automatic: official Bank of Israel rates when no manual rates
    # were sent, manual rates only otherwise. True = Bank of Israel rates,
    # with any manual rate overriding its own date. False = manual only.
    use_boi_rates: bool | None = None
    # {symbol: purchase date} for lots whose purchase is not visible in the
    # statement (opened in a prior year / transferred in). Without it those
    # lots are converted at the closing-date rate only and flagged.
    acquisition_dates: dict[str, date] = {}


def _apply_overrides(classified: list[ClassifiedItem], overrides: dict) -> list[ClassifiedItem]:
    field_overrides: dict[str, str | None] = overrides.get("field_overrides", {})
    out: list[ClassifiedItem] = []
    for item in classified:
        if item.source_id in field_overrides:
            item = item.model_copy(update={"nispach_d_field": field_overrides[item.source_id], "needs_review": False})
        out.append(item)
    return out


@router.post("/{statement_id}/appendix.xlsx")
def generate_appendix_xlsx(
    statement_id: str,
    payload: ReportRequest,
    user: UserORM = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> StreamingResponse:
    orm = session.get(StatementORM, statement_id)
    if orm is None:
        raise HTTPException(status_code=404, detail="Statement not found")
    statement = NormalizedStatement.model_validate(orm.normalized_statement_json)
    classified = [ClassifiedItem.model_validate(c) for c in orm.classified_items_json]
    classified = _apply_overrides(classified, orm.overrides_json or {})

    dividends_by_id = {f"{d.symbol} {d.pay_date.isoformat()}": d for d in statement.dividends}

    use_boi = payload.use_boi_rates if payload.use_boi_rates is not None else not payload.fx_rates
    if not use_boi and not payload.fx_rates:
        raise HTTPException(status_code=422, detail="יש להזין לפחות שער המרה אחד, או להשתמש בשערי בנק ישראל.")

    rates: dict[tuple[Currency, date], float] = {}
    if use_boi:
        needed_dates = [c.value_date for c in classified] + [c.open_date for c in classified if c.open_date]
        needed_dates += list(payload.acquisition_dates.values())
        try:
            rates.update(fetch_rates_covering({c.currency for c in classified}, needed_dates))
        except BoiRatesUnavailable as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
    rates.update({(r.currency, r.on_date): r.rate for r in payload.fx_rates})
    if use_boi:
        rate_source = "בנק ישראל - שער יציג לכל יום עסקים" + (" (עם שערים שהוזנו ידנית)" if payload.fx_rates else "")
    else:
        rate_source = "שערים שהוזנו ידנית"
    currency_service = CurrencyService(rates)

    bracket_overrides = (orm.overrides_json or {}).get("bracket_overrides", {})

    try:
        report = build_appendix_report(
            statement,
            classified,
            dividends_by_id,
            currency_service,
            bracket_overrides,
            payload.acquisition_dates,
            rate_source,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    xlsx_bytes = build_appendix_workbook(report)
    filename = f"nespach_ezer_{statement_id[:8]}.xlsx"
    log_activity(session, user, "appendix.download", target_type="statement", target_id=statement_id)
    return StreamingResponse(
        io.BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
