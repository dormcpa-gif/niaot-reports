"""Builds the two deliverables described in the plan:
1. the appendix (נספח עזר) -- Nispach C + Nispach D field totals.
2. the explanation/audit report -- every source row, its converted ILS
   amount, and the field it landed in.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.mapping.classification import ClassifiedItem
from app.mapping.nispach_c import NispachCResult, build_nispach_c
from app.mapping.nispach_d import NispachDResult, build_nispach_d
from app.models.transactions import Currency, Dividend, NormalizedStatement
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


class AppendixReport(BaseModel):
    statement_id: str
    nispach_c: NispachCResult
    nispach_d: NispachDResult
    explanation_rows: list[ExplanationRow]


def _source_table_and_text(statement: NormalizedStatement, kind: str, source_id: str) -> tuple[str, str]:
    pools = {
        "dividend": statement.dividends,
        "interest": statement.interest,
        "trade": statement.trades,
        "fee": statement.fees,
    }
    for record in pools.get(kind, []):
        candidate_id = _record_source_id(record, kind)
        if candidate_id == source_id:
            return record.source.table_name, record.source.row_text
    return "", ""


def _record_source_id(record, kind: str) -> str:
    if kind == "dividend":
        return f"{record.symbol} {record.pay_date.isoformat()}"
    if kind == "interest":
        return f"{record.description} {record.value_date.isoformat()}"
    if kind == "trade":
        return f"{record.symbol} ({record.holding_term.value}-term, {record.close_date.isoformat()})"
    if kind == "fee":
        return f"{record.description} {record.value_date.isoformat()}"
    raise ValueError(kind)


def build_appendix_report(
    statement: NormalizedStatement,
    classified: list[ClassifiedItem],
    dividends_by_id: dict[str, Dividend],
    currency_service: CurrencyService,
    bracket_overrides: dict[str, str] | None = None,
) -> AppendixReport:
    dividend_and_interest_items = [c for c in classified if c.source_kind in ("dividend", "interest")]
    trade_items = [c for c in classified if c.source_kind == "trade"]

    nispach_d = build_nispach_d(dividend_and_interest_items, dividends_by_id, currency_service)
    nispach_c = build_nispach_c(trade_items, statement.sale_proceeds_by_symbol, currency_service, bracket_overrides)

    explanation_rows: list[ExplanationRow] = []
    for item in classified:
        table_name, row_text = _source_table_and_text(statement, item.source_kind, item.source_id)
        conv = currency_service.convert(item.amount_source_ccy, Currency.USD, item.value_date)
        if item.source_kind == "trade":
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
                fx_rate=conv.rate_used,
                fx_rate_is_fallback=conv.is_fallback,
                amount_ils=conv.ils_amount,
                target_field=target_field,
                needs_review=item.needs_review,
                review_reason=item.review_reason,
            )
        )

    return AppendixReport(
        statement_id=statement.statement_id,
        nispach_c=nispach_c,
        nispach_d=nispach_d,
        explanation_rows=explanation_rows,
    )
