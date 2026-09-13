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

Validated against one real, professionally-prepared 1040 (tax-prep
software output) -- unlike the earlier revision of this module (which
was pure guesswork from the IRS's own blank-form line numbers), the
patterns below reflect an actual quirk of how that software's PDF
extracts as text:
  - The printed line-number column ("2a", "2b", "3a", "3b"...) and each
    line's description text are NOT adjacent in extraction order -- a
    naive "^2b Taxable interest" anchor never matches. What DOES appear
    reliably is the description phrase itself immediately followed by a
    run of "~" leader characters and then the dollar amount, e.g.
    "Ordinary dividends ~~~~~ 6,472." -- so labels below are matched as
    a substring anywhere on a line, and the amount is the LAST number
    that appears after the label on that same line (a line can contain
    more than one label+amount pair, e.g. "Qualified dividends ~~~~
    1,556. Ordinary dividends ~~~~~ 6,472.").
  - A filled-in whole-dollar amount can print with no cents digits at
    all ("6,472." not "6,472.00") -- the amount pattern allows 0-2
    digits after the decimal point, not exactly 2.
  - A blank/zero line (e.g. this taxpayer's $0 taxable interest: "...
    Tax-exempt interest ~~~ Taxable interest ~~~~~~" with nothing after
    it) correctly yields no match here -- treated as "not present",
    same as before.

This was validated against only ONE real filer's software output, so a
different tax-prep product could still lay the same lines out
differently -- treat results with the same scrutiny as eToro/Schwab/K-1,
just with one real data point behind it instead of zero.

Lines extracted (2025 form revision):
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

_NUM_RE = re.compile(r"\(?-?[\d,]+\.\d{0,2}\)?")

_INTEREST_LABELS = ("Taxable interest",)
_DIVIDEND_LABELS = ("Ordinary dividends",)
_CAPITAL_GAIN_LABELS = ("Capital gain or (loss)",)


def _to_float(text: str) -> float:
    text = text.strip().rstrip(".")
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    if not text:
        return 0.0
    value = float(text.replace(",", ""))
    return -value if negative else value


def _find_line_amount(pages_text: list[str], *labels: str) -> tuple[float, int, str] | None:
    """Returns (amount, page_number, row_text) for the first line (across
    all pages, in order) containing one of the given labels with a
    number somewhere after it -- see module docstring for why matching
    is substring-anywhere-on-the-line rather than anchored at the start."""
    for page_num, text in enumerate(pages_text, start=1):
        for line in text.splitlines():
            for label in labels:
                idx = line.find(label)
                if idx == -1:
                    continue
                remainder = line[idx + len(label) :]
                matches = list(_NUM_RE.finditer(remainder))
                if matches:
                    return _to_float(matches[-1].group(0)), page_num, line.strip()
    return None


def _find_tax_year(full_text: str) -> int | None:
    m = re.search(r"For the year Jan\.?\s*1\s*-\s*Dec\.?\s*31,\s*(\d{4})", full_text)
    if m:
        return int(m.group(1))
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
        )


class Form1040Parser:
    broker_name = "Form 1040 (US Individual Income Tax Return)"

    def parse(self, file_bytes: bytes, statement_id: str) -> NormalizedStatement:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            if not pdf.pages:
                raise ValueError("קובץ ה-PDF ריק (0 עמודים).")
            pages_text = [p.extract_text() or "" for p in pdf.pages]

        full_text = "\n".join(pages_text)
        _sanity_check_is_1040(full_text)
        tax_year = _find_tax_year(full_text) or date.today().year - 1
        year_end = date(tax_year, 12, 31)
        year_start = date(tax_year, 1, 1)

        interest_match = _find_line_amount(pages_text, *_INTEREST_LABELS)
        dividend_match = _find_line_amount(pages_text, *_DIVIDEND_LABELS)
        capital_gain_match = _find_line_amount(pages_text, *_CAPITAL_GAIN_LABELS)

        interest: list[InterestItem] = []
        dividends: list[Dividend] = []
        trades: list[Trade] = []

        if interest_match:
            amount, page_num, row_text = interest_match
            interest.append(
                InterestItem(
                    value_date=year_end,
                    description="Form 1040 Line 2b: Taxable interest (aggregate, all payers)",
                    amount=amount,
                    currency=Currency.USD,
                    source=SourceRef(statement_id=statement_id, page=page_num, table_name="Form 1040", row_text=row_text),
                )
            )
        if dividend_match:
            amount, page_num, row_text = dividend_match
            dividends.append(
                Dividend(
                    pay_date=year_end,
                    symbol="1040 Line 3b",
                    description="Form 1040 Line 3b: Ordinary dividends (aggregate, all payers)",
                    gross_amount=amount,
                    currency=Currency.USD,
                    source=SourceRef(statement_id=statement_id, page=page_num, table_name="Form 1040", row_text=row_text),
                )
            )
        if capital_gain_match:
            amount, page_num, row_text = capital_gain_match
            trades.append(
                Trade(
                    symbol="1040 Line 7",
                    close_date=year_end,
                    proceeds=0.0,
                    cost_basis=0.0,
                    realized_pnl=round(amount, 2),
                    holding_term=HoldingTerm.SHORT,
                    currency=Currency.USD,
                    source=SourceRef(statement_id=statement_id, page=page_num, table_name="Form 1040", row_text=row_text),
                )
            )

        if not interest and not dividends and not trades:
            raise ValueError(
                "לא זוהו שורות 2b (ריבית) / 3b (דיבידנד) / 7 (רווח הון) בטופס. ייתכן שהמבנה בפועל של טופס זה "
                "שונה מהצפוי (תלוי בתוכנת ההכנה שהפיקה את ה-PDF), או שכל שלושת השדות הללו ריקים/אפס אצל נישום זה. "
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
