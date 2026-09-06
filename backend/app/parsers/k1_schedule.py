"""Parser for US Schedule K-1 (Form 1065) -- partnership income allocated
to an individual partner.

Grounding note (read before trusting this like the IBKR parser): unlike
IBKR, we have **no real K-1 to test against**. Schedule K-1 (Form 1065)
is a standardized IRS form with fixed box numbers/labels, which is more
consistent across filers than a brokerage statement's free-form layout
-- but PDF text-extraction order for a form laid out as label/box pairs
(rather than a flowing table) is still not guaranteed to put a box's
label and its dollar value on one extractable line the way we assume
below. Treat every result with the same extra scrutiny as eToro/Schwab.

Scope, deliberately narrow -- only the boxes with an unambiguous,
single-number meaning are extracted:
  - Box 5: Interest income -> InterestItem
  - Box 6a: Ordinary dividends -> Dividend (gross)
  - Box 8: Net short-term capital gain (loss) -> Trade (short-term)
  - Box 9a: Net long-term capital gain (loss) -> Trade (long-term)

Explicitly OUT of scope: Box 16 / Schedule K-3 foreign transaction
detail (foreign tax paid, country, income re-sourced by treaty, etc).
That figure is a single aggregate covering a mix of the above income
types, not cleanly attributable to one box by a text-pattern parse --
guessing an allocation would be exactly the kind of silent wrong number
this system avoids. The accountant must bring in Box 16/Schedule K-3
foreign tax credit detail manually from the K-1/K-3 itself.

Each box is looked for independently; if a box's label text isn't found
at all, it's simply treated as zero/absent (many K-1s legitimately have
blank boxes) rather than raising an error. An error is only raised if
the document doesn't look like a K-1 at all, or if literally none of
the four boxes were found (suggesting the layout didn't match our
assumptions and nothing was extracted).
"""

from __future__ import annotations

import re
from datetime import date

import pdfplumber
import io

from app.models.transactions import (
    Currency,
    Dividend,
    HoldingTerm,
    InterestItem,
    NormalizedStatement,
    SourceRef,
    Trade,
)

_NUM = r"\(?-?[\d,]+\.\d{2}\)?"


def _to_float(text: str) -> float:
    text = text.strip()
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    value = float(text.replace(",", ""))
    return -value if negative else value


def _find_box_amount(full_text: str, *labels: str) -> float | None:
    """Search line-by-line for one of the given box labels, and pull the
    trailing dollar amount from the same line, or -- if that line ends
    right after the label with no number -- the next non-blank line
    (some renderers wrap the box's answer to its own line)."""
    lines = full_text.splitlines()
    label_re = re.compile(r"^\s*(?:" + "|".join(re.escape(l) for l in labels) + r")(.*)$", re.IGNORECASE)
    amount_re = re.compile(r"(" + _NUM + r")\s*$")
    for idx, line in enumerate(lines):
        m = label_re.match(line.strip())
        if not m:
            continue
        tail = m.group(1)
        amt_m = amount_re.search(tail)
        if amt_m:
            return _to_float(amt_m.group(1))
        for lookahead in lines[idx + 1 : idx + 3]:
            amt_m = amount_re.search(lookahead.strip())
            if amt_m:
                return _to_float(amt_m.group(1))
    return None


def _find_tax_year(full_text: str) -> int | None:
    m = re.search(r"(?:for calendar year|tax year)\s*(\d{4})", full_text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # Fall back to the first 4-digit year mentioned anywhere in the
    # document -- reasonable once _sanity_check_is_k1 has already
    # confirmed this is a K-1, since the tax year is always printed
    # prominently near the top (order relative to "Schedule K-1" varies
    # by renderer, so we don't anchor to it).
    m = re.search(r"\b(20\d{2})\b", full_text)
    if m:
        return int(m.group(1))
    return None


def _sanity_check_is_k1(full_text: str) -> None:
    if "Schedule K-1" not in full_text or "1065" not in full_text:
        raise ValueError(
            "הקובץ אינו נראה כמו Schedule K-1 (Form 1065) - לא נמצאו הכותרות הצפויות. "
            "פרסר זה טרם אומת מול מסמך אמיתי -- ראו הערת האמינות במסמך."
        )


class K1ScheduleParser:
    broker_name = "Schedule K-1 (Form 1065)"

    def parse(self, file_bytes: bytes, statement_id: str) -> NormalizedStatement:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            if not pdf.pages:
                raise ValueError("קובץ ה-PDF ריק (0 עמודים).")
            full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)

        _sanity_check_is_k1(full_text)
        tax_year = _find_tax_year(full_text) or date.today().year - 1
        year_end = date(tax_year, 12, 31)
        year_start = date(tax_year, 1, 1)

        source = SourceRef(statement_id=statement_id, page=1, table_name="Schedule K-1 Part III", row_text="")

        interest_amount = _find_box_amount(full_text, "5 Interest income", "5. Interest income", "5 Interest Income")
        dividend_amount = _find_box_amount(
            full_text, "6a Ordinary dividends", "6a. Ordinary dividends", "6a Ordinary Dividends"
        )
        short_term_gain = _find_box_amount(
            full_text,
            "8 Net short-term capital gain",
            "8. Net short-term capital gain",
            "8 Net short-term capital gain (loss)",
        )
        long_term_gain = _find_box_amount(
            full_text,
            "9a Net long-term capital gain",
            "9a. Net long-term capital gain",
            "9a Net long-term capital gain (loss)",
        )

        interest: list[InterestItem] = []
        dividends: list[Dividend] = []
        trades: list[Trade] = []

        if interest_amount:
            interest.append(
                InterestItem(
                    value_date=year_end,
                    description="K-1 Box 5: Interest income",
                    amount=interest_amount,
                    currency=Currency.USD,
                    source=source,
                )
            )
        if dividend_amount:
            dividends.append(
                Dividend(
                    pay_date=year_end,
                    symbol="K-1 Box 6a",
                    description="K-1 Box 6a: Ordinary dividends",
                    gross_amount=dividend_amount,
                    currency=Currency.USD,
                    source=source,
                )
            )
        if short_term_gain:
            trades.append(
                Trade(
                    symbol="K-1 Box 8",
                    close_date=year_end,
                    proceeds=0.0,
                    cost_basis=0.0,
                    realized_pnl=round(short_term_gain, 2),
                    holding_term=HoldingTerm.SHORT,
                    currency=Currency.USD,
                    source=source,
                )
            )
        if long_term_gain:
            trades.append(
                Trade(
                    symbol="K-1 Box 9a",
                    close_date=year_end,
                    proceeds=0.0,
                    cost_basis=0.0,
                    realized_pnl=round(long_term_gain, 2),
                    holding_term=HoldingTerm.LONG,
                    currency=Currency.USD,
                    source=source,
                )
            )

        if not interest and not dividends and not trades:
            raise ValueError(
                "לא זוהה אף אחד מהתיבות 5 / 6a / 8 / 9a במסמך. פרסר K-1 זה מבוסס על מבנה הטופס הרשמי של "
                "רשות המסים האמריקאית (IRS) אך טרם נבדק מול מסמך אמיתי -- ייתכן שסדר חילוץ הטקסט מה-PDF "
                "שונה מהצפוי. יש לבדוק ידנית את הסכומים בטופס ולהזין אותם ידנית אם הפרסר לא זיהה אותם."
            )

        return NormalizedStatement(
            statement_id=statement_id,
            broker=self.broker_name,
            period_start=year_start,
            period_end=year_end,
            base_currency=Currency.USD,
            dividends=dividends,
            interest=interest,
            trades=trades,
            fees=[],
            sale_proceeds_by_symbol={},
        )
