"""Parser for Charles Schwab brokerage account statement PDFs.

Grounding note (read before trusting this like the IBKR parser): unlike
IBKR, we have **no real Schwab statement to test against**. The only
public reference found was Schwab's own statement guide
(schwab.com/resource/statement-guide), which shows the "Transactions"
table as a scanned image inside the PDF (not extractable text) --
so even the column layout below is inferred from that guide's
description, not verified against real extracted text. Treat every
result from this parser with significantly more scrutiny than IBKR,
and even more than eToro (which at least has real open-source parsers
documenting its columns from live exports).

Per the guide, the "Transactions" table has these columns, in order:
Date | Category (e.g. "Dividends & Interest", "Trades") | Action
(e.g. "Qualified Dividend", "Bank Interest", "Foreign Tax Paid",
"Buy", "Sell") | Symbol/CUSIP | Description | Quantity | Price/Rate |
Charges & Interest | Amount.

TD Ameritrade accounts were migrated onto Schwab's platform/statement
format (the TD Ameritrade brand was retired in 2024), so the same
parser is registered for both broker keys -- see extraction_service.py.

Scope deliberately limited to dividends + interest: the Transactions
table shows sale proceeds but no cost basis, so a "Sell" row alone
cannot yield a real realized gain/loss the way IBKR's Performance
Summary or a 1099-B can. Inventing a $0 gain would be exactly the kind
of silent wrong number this system is built to avoid -- so this parser
does not attempt capital gains at all. Nispach C for a Schwab/TD
Ameritrade account currently needs the accountant to bring in cost
basis separately (e.g. from Schwab's own Realized Gain/Loss report or
the client's 1099-B).

This parser only recognizes whole text lines that look like one of the
known Action keywords followed by a trailing dollar amount; it does not
attempt to reconstruct the full column grid (fragile without a real
sample to validate column boundaries against). Anything it cannot
confidently match is simply not extracted -- it does not guess.
"""

from __future__ import annotations

import io
import re
from datetime import date, datetime

import pdfplumber

from app.models.transactions import Currency, Dividend, InterestItem, NormalizedStatement, SourceRef

_DATE = r"\d{1,2}/\d{1,2}/\d{4}"
_NUM = r"-?\$?[\d,]+\.\d{2}"

_PERIOD_RE = re.compile(
    r"(?:Statement Period|Activity for)\s+(" + _DATE + r")\s*(?:-|through|to)\s*(" + _DATE + r")",
    re.IGNORECASE,
)

_DIVIDEND_ACTIONS = ("Qualified Dividend", "Cash Dividend", "Ordinary Dividend", "Dividend")
_INTEREST_ACTIONS = ("Bank Interest", "Credit Interest", "Margin Interest")

_TX_LINE_RE = re.compile(
    r"^(?P<date>" + _DATE + r")\s+.*?\b"
    r"(?P<action>" + "|".join(re.escape(a) for a in (*_DIVIDEND_ACTIONS, *_INTEREST_ACTIONS)) + r")\b\s+"
    r"(?:(?P<symbol>[A-Z][A-Z0-9.]{0,9})\s+)?"
    r"(?P<desc>.*?)\s*"
    r"(?P<amount>" + _NUM + r")\s*$"
)


def _to_float(text: str) -> float:
    return float(text.replace("$", "").replace(",", ""))


def _parse_date(text: str) -> date:
    return datetime.strptime(text, "%m/%d/%Y").date()


def _sanity_check_is_schwab_statement(full_text: str) -> None:
    if "Schwab" not in full_text and "TD Ameritrade" not in full_text:
        raise ValueError(
            "הקובץ אינו נראה כמו דוח חשבון של Charles Schwab / TD Ameritrade "
            "(לא נמצאה הכותרת הצפויה בעמוד הראשון). פרסר זה טרם אומת מול דוח אמיתי -- ראו הערת האמינות במסמך."
        )


def _parse_period(full_text: str) -> tuple[date, date]:
    m = _PERIOD_RE.search(full_text)
    if not m:
        raise ValueError("לא זוהה טווח תאריכים בדוח. ודאו שזהו קובץ Statement תקין של Schwab / TD Ameritrade.")
    return _parse_date(m.group(1)), _parse_date(m.group(2))


def parse_transactions_text(text: str, statement_id: str, page: int) -> tuple[list[Dividend], list[InterestItem]]:
    dividends: list[Dividend] = []
    interest: list[InterestItem] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        m = _TX_LINE_RE.match(line)
        if not m:
            continue
        action = m.group("action")
        amount = _to_float(m.group("amount"))
        value_date = _parse_date(m.group("date"))
        source = SourceRef(statement_id=statement_id, page=page, table_name="Transactions", row_text=line)
        if action in _DIVIDEND_ACTIONS:
            dividends.append(
                Dividend(
                    pay_date=value_date,
                    symbol=(m.group("symbol") or m.group("desc") or "Unknown").strip(),
                    description=action,
                    gross_amount=amount,
                    currency=Currency.USD,
                    source=source,
                )
            )
        elif action in _INTEREST_ACTIONS:
            interest.append(
                InterestItem(
                    value_date=value_date,
                    description=f"{action} {m.group('desc')}".strip(),
                    amount=amount,
                    currency=Currency.USD,
                    source=source,
                )
            )
    return dividends, interest


class SchwabStatementParser:
    broker_name = "Charles Schwab / TD Ameritrade"

    def parse(self, file_bytes: bytes, statement_id: str) -> NormalizedStatement:
        dividends: list[Dividend] = []
        interest: list[InterestItem] = []

        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            if not pdf.pages:
                raise ValueError("קובץ ה-PDF ריק (0 עמודים).")
            full_first_page = pdf.pages[0].extract_text() or ""
            _sanity_check_is_schwab_statement(full_first_page)
            full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)
            period_start, period_end = _parse_period(full_first_page or full_text)

            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                d, it = parse_transactions_text(text, statement_id, i + 1)
                dividends.extend(d)
                interest.extend(it)

        if not dividends and not interest:
            raise ValueError(
                "לא זוהו שורות דיבידנד/ריבית מוכרות בדוח. פרסר Schwab/TD Ameritrade זה מבוסס על תיעוד ציבורי "
                "בלבד וטרם נבדק מול דוח אמיתי -- ייתכן שהמבנה בפועל שונה. יש לבדוק ידנית או לפנות להרחבת הפרסר."
            )

        return NormalizedStatement(
            statement_id=statement_id,
            broker=self.broker_name,
            period_start=period_start,
            period_end=period_end,
            base_currency=Currency.USD,
            dividends=dividends,
            interest=interest,
            trades=[],
            fees=[],
            sale_proceeds_by_symbol={},
        )
