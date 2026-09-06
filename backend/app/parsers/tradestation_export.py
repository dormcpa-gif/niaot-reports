"""Parser for TradeStation CSV exports (Tax Center / account activity).

Grounding note (read before trusting this like the IBKR parser): unlike
IBKR, we have **no real TradeStation export to test against**, and
unlike eToro, we could not find an actively-maintained open-source tool
that documents TradeStation's exact column headers from a live export.
The column names below follow the generic layout TradeStation's own
help documentation describes for its Tax Center "Realized Gain/Loss"
CSV (Symbol/Description/Quantity/Date Acquired/Date Sold/Proceeds/Cost
Basis/Wash Sale Loss Disallowed/Gain or Loss/Term) and for a typical
brokerage cash-activity CSV (Date/Description/Amount/Type). Treat every
result from this parser with the same extra scrutiny as eToro/Schwab
until it's been run against a real export.

TradeStation exports two separate CSV files rather than one workbook
with multiple sheets, so unlike eToro (one file, two known sheet names)
this parser inspects whichever single CSV it's given and detects, from
its header row, whether it's the Gain/Loss export or the cash-activity
export -- one upload call per file, same broker key ("TRADESTATION").
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime

from app.models.transactions import (
    Currency,
    Dividend,
    HoldingTerm,
    InterestItem,
    NormalizedStatement,
    SourceRef,
    Trade,
)

_GAIN_LOSS_HEADERS = {"Symbol", "Date Acquired", "Date Sold", "Proceeds", "Cost Basis", "Gain/Loss"}
_CASH_ACTIVITY_HEADERS = {"Date", "Description", "Amount", "Type"}

_DATE_FORMATS = ("%m/%d/%Y", "%Y-%m-%d")

_DIVIDEND_TYPES = {"dividend", "qualified dividend", "cash dividend"}
_INTEREST_TYPES = {"credit interest", "debit interest", "interest income", "interest"}


def _normalize_header(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


def _parse_csv_date(text: str) -> date | None:
    text = (text or "").strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount(text: str) -> float | None:
    text = (text or "").strip().replace("$", "").replace(",", "")
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    try:
        value = float(text)
    except ValueError:
        return None
    return -value if negative else value


def _parse_gain_loss_rows(
    reader: csv.DictReader, statement_id: str
) -> tuple[list[Trade], list[date]]:
    trades: list[Trade] = []
    dates: list[date] = []
    for row in reader:
        close_date = _parse_csv_date(row.get("Date Sold", ""))
        proceeds = _parse_amount(row.get("Proceeds", ""))
        cost_basis = _parse_amount(row.get("Cost Basis", ""))
        gain_loss = _parse_amount(row.get("Gain/Loss", ""))
        symbol = (row.get("Symbol") or "").strip()
        if close_date is None or gain_loss is None or not symbol:
            continue
        term_text = (row.get("Term") or "").strip().lower()
        term = HoldingTerm.LONG if term_text.startswith("long") else HoldingTerm.SHORT
        dates.append(close_date)
        trades.append(
            Trade(
                symbol=symbol,
                close_date=close_date,
                proceeds=proceeds or 0.0,
                cost_basis=cost_basis or 0.0,
                realized_pnl=round(gain_loss, 2),
                holding_term=term,
                currency=Currency.USD,
                source=SourceRef(
                    statement_id=statement_id,
                    page=0,
                    table_name="Realized Gain/Loss",
                    row_text=str(row),
                ),
            )
        )
    return trades, dates


def _parse_cash_activity_rows(
    reader: csv.DictReader, statement_id: str
) -> tuple[list[Dividend], list[InterestItem], list[date]]:
    dividends: list[Dividend] = []
    interest: list[InterestItem] = []
    dates: list[date] = []
    for row in reader:
        value_date = _parse_csv_date(row.get("Date", ""))
        amount = _parse_amount(row.get("Amount", ""))
        activity_type = (row.get("Type") or "").strip().lower()
        description = (row.get("Description") or "").strip()
        if value_date is None or amount is None:
            continue
        dates.append(value_date)
        source = SourceRef(statement_id=statement_id, page=0, table_name="Cash Activity", row_text=str(row))
        if activity_type in _DIVIDEND_TYPES:
            symbol_match = re.match(r"^([A-Z][A-Z0-9.]{0,9})\b", description)
            dividends.append(
                Dividend(
                    pay_date=value_date,
                    symbol=symbol_match.group(1) if symbol_match else description or "Unknown",
                    description=description or activity_type,
                    gross_amount=amount,
                    currency=Currency.USD,
                    source=source,
                )
            )
        elif activity_type in _INTEREST_TYPES:
            interest.append(
                InterestItem(
                    value_date=value_date,
                    description=description or activity_type,
                    amount=amount,
                    currency=Currency.USD,
                    source=source,
                )
            )
    return dividends, interest, dates


class TradeStationExportParser:
    broker_name = "TradeStation"

    def parse(self, file_bytes: bytes, statement_id: str) -> NormalizedStatement:
        try:
            text = file_bytes.decode("utf-8-sig")
        except UnicodeDecodeError as e:
            raise ValueError(f"לא ניתן היה לפענח את הקובץ כטקסט/CSV תקין (שגיאה: {e}).") from e

        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise ValueError("קובץ ה-CSV ריק או ללא שורת כותרות.")
        headers = {_normalize_header(h) for h in reader.fieldnames}

        dividends: list[Dividend] = []
        interest: list[InterestItem] = []
        trades: list[Trade] = []
        all_dates: list[date] = []

        if _GAIN_LOSS_HEADERS.issubset(headers):
            trades, dates = _parse_gain_loss_rows(reader, statement_id)
            all_dates.extend(dates)
        elif _CASH_ACTIVITY_HEADERS.issubset(headers):
            dividends, interest, dates = _parse_cash_activity_rows(reader, statement_id)
            all_dates.extend(dates)
        else:
            raise ValueError(
                "לא זוהו כותרות עמודות מוכרות בקובץ ה-CSV. יש להעלות את קובץ ה-CSV של 'Realized Gain/Loss' "
                "(עמודות כגון Symbol, Date Sold, Proceeds, Cost Basis, Gain/Loss) או של פעילות מזומן "
                "(עמודות Date, Description, Amount, Type) מ-TradeStation. "
                f"כותרות שנמצאו בפועל: {', '.join(sorted(headers))}"
            )

        if not all_dates:
            raise ValueError(
                "לא נמצאו שורות נתונים תקינות בקובץ (כותרות זוהו אך אין שורות עם תאריך/סכום תקינים)."
            )

        return NormalizedStatement(
            statement_id=statement_id,
            broker=self.broker_name,
            period_start=min(all_dates),
            period_end=max(all_dates),
            base_currency=Currency.USD,
            dividends=dividends,
            interest=interest,
            trades=trades,
            fees=[],
            sale_proceeds_by_symbol={},
        )
