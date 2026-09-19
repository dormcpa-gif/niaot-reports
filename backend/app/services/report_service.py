"""Builds the two deliverables described in the plan:
1. the appendix (נספח עזר) -- Nispach C + Nispach D field totals.
2. the explanation/audit report -- every source row, its converted ILS
   amount, and the field it landed in.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from app.mapping.capital_gain_fx import convert_trade_item
from app.mapping.classification import ClassifiedItem
from app.mapping.nispach_c import NispachCResult, build_nispach_c
from app.mapping.nispach_d import NispachDResult, build_nispach_d
from app.models.transactions import Dividend, NormalizedStatement
from app.services.currency_service import CurrencyService


class ExplanationRow(BaseModel):
    source_kind: str
    source_id: str
    source_table: str
    source_row_text: str
    amount_source_ccy: float
    fx_rate: float
    fx_rate_is_fallback: bool
    amount_ils: float
    target_field: str | None  # Nispach D field, or "נספח ג'" for capital gains, or None for fees
    needs_review: bool
    review_reason: str | None
    calc_note: str | None = None  # how a capital-gain lot's ILS figure was derived


class AppendixReport(BaseModel):
    statement_id: str
    nispach_c: NispachCResult
    nispach_d: NispachDResult
    explanation_rows: list[ExplanationRow]
    rate_source: str = ""  # where the FX rates came from, shown in the workbook
    warnings: list[str] = []  # statement-level findings (e.g. a symbol that did not reconcile)


def _records_by_kind(statement: NormalizedStatement) -> dict[str, list]:
    return {
        "dividend": statement.dividends,
        "interest": statement.interest,
        "trade": statement.trades,
        "fee": statement.fees,
    }


def build_appendix_report(
    statement: NormalizedStatement,
    classified: list[ClassifiedItem],
    dividends_by_id: dict[str, Dividend],
    currency_service: CurrencyService,
    bracket_overrides: dict[str, str] | None = None,
    acquisition_dates: dict[str, date] | None = None,
    rate_source: str = "",
) -> AppendixReport:
    dividend_and_interest_items = [c for c in classified if c.source_kind in ("dividend", "interest")]
    trade_items = [c for c in classified if c.source_kind == "trade"]

    nispach_d = build_nispach_d(dividend_and_interest_items, dividends_by_id, currency_service)
    nispach_c = build_nispach_c(
        trade_items,
        statement.sale_proceeds_by_symbol,
        currency_service,
        bracket_overrides,
        statement.base_currency,
        acquisition_dates,
    )

    # classify_*() in extraction_service.extract_and_classify() produces
    # exactly one ClassifiedItem per raw record, in the same order as
    # statement.<kind> -- match them up by position instead of
    # recomputing a "natural" source_id and string-matching it, which
    # silently breaks for any item whose source_id was disambiguated
    # (see extraction_service._dedupe_source_id) because two records
    # shared the same natural label+date.
    records_by_kind = _records_by_kind(statement)
    next_index_by_kind: dict[str, int] = {}

    explanation_rows: list[ExplanationRow] = []
    for item in classified:
        idx = next_index_by_kind.get(item.source_kind, 0)
        next_index_by_kind[item.source_kind] = idx + 1
        records = records_by_kind.get(item.source_kind, [])
        record = records[idx] if idx < len(records) else None
        table_name = record.source.table_name if record else ""
        row_text = record.source.row_text if record else ""
        conv = currency_service.convert(item.amount_source_ccy, item.currency, item.value_date)
        fx_rate, amount_ils, calc_note = conv.rate_used, conv.ils_amount, None
        if item.source_kind == "trade":
            ils = convert_trade_item(item, currency_service, acquisition_dates)
            fx_rate, amount_ils = ils.close_rate, ils.real_ils
            if item.lot_level and ils.buy_rate is not None:
                calc_note = (
                    f"נומינלי ₪{ils.nominal_ils:,.2f} | אינפלציוני (פטור) ₪{ils.inflationary_ils:,.2f} | ריאלי ₪{ils.real_ils:,.2f}; "
                    f"שער רכישה {ils.buy_rate}, שער מכירה {ils.sell_rate}, שער סגירה {ils.close_rate}"
                )
            else:
                calc_note = ils.note
        if item.source_kind == "trade" and item.asset_class == "Forex":
            target_field = "לא נכלל בנספח ג' - רווח ממט\"ח (לבדיקת רו\"ח)"
        elif item.source_kind == "trade":
            target_field = "נספח ג' (רווח הון מני\"ע)"
        elif item.nispach_d_field:
            target_field = f"נספח ד' שדה {item.nispach_d_field}"
        else:
            target_field = None
        explanation_rows.append(
            ExplanationRow(
                source_kind=item.source_kind,
                source_id=item.source_id,
                source_table=table_name,
                source_row_text=row_text,
                amount_source_ccy=item.amount_source_ccy,
                fx_rate=fx_rate,
                fx_rate_is_fallback=conv.is_fallback,
                amount_ils=amount_ils,
                target_field=target_field,
                needs_review=item.needs_review,
                review_reason=item.review_reason,
                calc_note=calc_note,
            )
        )

    return AppendixReport(
        statement_id=statement.statement_id,
        nispach_c=nispach_c,
        nispach_d=nispach_d,
        explanation_rows=explanation_rows,
        rate_source=rate_source,
        warnings=list(statement.warnings),
    )
