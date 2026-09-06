"""Parser for US Form 1040 (individual income tax return) -- used only as
a last-resort summary source when no itemized broker statement exists
for the client's US-source income.

*** IMPORTANT -- READ BEFORE USING ***

Form 1040 is an *aggregate* summary: its dividend/interest/capital-gain
lines already total every 1099 the taxpayer received for the year, with
no per-payer breakdown and no split by instrument/country. Uploading a
1040 for the SAME account/year that an IBKR, Schwab, eToro, TradeStation
or K-1 statement was already uploaded for **will double-count income** --
this parser does not (and cannot, from a 1040 alone) detect that overlap.
Use it only when the accountant has no itemized broker statement to work
from and the 1040 is the only source available, and never combine it
with an itemized statement covering the same income for the same year.

Grounding note (read before trusting this like the IBKR parser): unlike
IBKR, we have **no real signed 1040 to test against**. Form 1040 is a
standardized IRS form with fixed line numbers, but PDF text-extraction
order for a form laid out as label/box pairs is not guaranteed to match
what we assume below. Treat every result with the same extra scrutiny
as eToro/Schwab/K-1.

Lines extracted (2023/2024 revision line numbers):
  - Line 2b: Taxable interest -> InterestItem
  - Line 3b: Ordinary dividends -> Dividend (gross; includes qualified
    dividends from line 3a, so 3a is not extracted separately to avoid
    double-counting the same dollars twice)
  - Line 7: Capital gain or (loss) -> Trade (a single aggregate figure;
    holding_term is NOT meaningful here since 1040 doesn't split
    short/long -- recorded as short-term only so it appears once, not
    twice, in downstream totals; the accountant must break this down
    using the taxpayer's actual Schedule D / Form 8949 if a bracket
    split is needed for Nispach C)
"""

from __future__ import annotations

import io
import re
from datetime import date

import pdfplumber

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


def _find_line_amount(full_text: str, *labels: str) -> float | None:
    lines = full_text.splitlines()
    label_re = re.compile(r"^\s*(?:" + "|".join(re.escape(l) for l in labels) + r")(.*)$", re.IGNORECASE)
    amount_re = re.compile(r"(" + _NUM + r")\s*$")
    for idx, line in enumerate(lines):
        m = label_re.match(line.strip())
        if not m:
            continue
        amt_m = amount_re.search(m.group(1))
        if amt_m:
            return _to_float(amt_m.group(1))
        for lookahead in lines[idx + 1 : idx + 3]:
            amt_m = amount_re.search(lookahead.strip())
            if amt_m:
                return _to_float(amt_m.group(1))
    return None


def _find_tax_year(full_text: str) -> int | None:
    m = re.search(r"(\d{4})\s+Form 1040", full_text)
    if m:
        return int(m.group(1))
    m = re.search(r"Form 1040\s*\((\d{4})\)", full_text)
    if m:
        return int(m.group(1))
    return None


def _sanity_check_is_1040(full_text: str) -> None:
    if "Form 1040" not in full_text or "U.S. Individual Income Tax Return" not in full_text:
        raise ValueError(
            "הקובץ אינו נראה כמו טופס 1040 (U.S. Individual Income Tax Return) - לא נמצאו הכותרות הצפויות. "
            "פרסר זה טרם אומת מול מסמך אמיתי -- ראו הערת האמינות במסמך."
        )


class Form1040Parser:
    broker_name = "Form 1040 (US Individual Income Tax Return)"

    def parse(self, file_bytes: bytes, statement_id: str) -> NormalizedStatement:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            if not pdf.pages:
                raise ValueError("קובץ ה-PDF ריק (0 עמודים).")
            full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)

        _sanity_check_is_1040(full_text)
        tax_year = _find_tax_year(full_text) or date.today().year - 1
        year_end = date(tax_year, 12, 31)
        year_start = date(tax_year, 1, 1)
        source = SourceRef(statement_id=statement_id, page=1, table_name="Form 1040", row_text="")

        interest_amount = _find_line_amount(full_text, "2b Taxable interest", "2b. Taxable interest")
        dividend_amount = _find_line_amount(full_text, "3b Ordinary dividends", "3b. Ordinary dividends")
        capital_gain = _find_line_amount(
            full_text, "7 Capital gain or (loss)", "7. Capital gain or (loss)", "7 Capital gain"
        )

        interest: list[InterestItem] = []
        dividends: list[Dividend] = []
        trades: list[Trade] = []

        if interest_amount:
            interest.append(
                InterestItem(
                    value_date=year_end,
                    description="Form 1040 Line 2b: Taxable interest (aggregate, all payers)",
                    amount=interest_amount,
                    currency=Currency.USD,
                    source=source,
                )
            )
        if dividend_amount:
            dividends.append(
                Dividend(
                    pay_date=year_end,
                    symbol="1040 Line 3b",
                    description="Form 1040 Line 3b: Ordinary dividends (aggregate, all payers)",
                    gross_amount=dividend_amount,
                    currency=Currency.USD,
                    source=source,
                )
            )
        if capital_gain:
            trades.append(
                Trade(
                    symbol="1040 Line 7",
                    close_date=year_end,
                    proceeds=0.0,
                    cost_basis=0.0,
                    realized_pnl=round(capital_gain, 2),
                    holding_term=HoldingTerm.SHORT,
                    currency=Currency.USD,
                    source=source,
                )
            )

        if not interest and not dividends and not trades:
            raise ValueError(
                "לא זוהו שורות 2b / 3b / 7 בטופס. פרסר 1040 זה מבוסס על מבנה הטופס הרשמי של רשות המסים "
                "האמריקאית (IRS) אך טרם נבדק מול מסמך אמיתי -- ייתכן שסדר חילוץ הטקסט מה-PDF שונה מהצפוי. "
                "יש לבדוק ידנית את הסכומים בטופס ולהזין אותם ידנית אם הפרסר לא זיהה אותם."
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
