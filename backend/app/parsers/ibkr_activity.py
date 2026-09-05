"""Parser for Interactive Brokers 'Activity Statement' PDFs.

Design notes (why it's built this way):

- IBKR lays the Dividends section out in the LEFT half of the page and
  Fees / Interest Accruals / Deposits & Withdrawals / Interest in the
  RIGHT half, on the page(s) where they overlap. pdfplumber's default
  `extract_text()` reads by vertical position, so on those pages the two
  columns get interleaved line-by-line and naive text flattening produces
  garbage (a fee-column token can end up glued onto the tail of a
  dividend row). We detect that layout and crop left/right before
  extracting text. Continuation pages (dividends only, no fee/interest
  block) are genuinely single-column full width, so they're read as-is.

- Trade lot dates in the raw "Trades" table wrap unpredictably (the
  Date/Time cell splits across the row it describes), which makes
  per-lot regex parsing fragile. IBKR's own
  "Realized & Unrealized Performance Summary" table instead gives one
  clean, non-wrapping line per symbol with realized Short-Term and
  Long-Term profit/loss already split out — that's what we parse for
  capital gains instead of reconstructing trades ourselves.

- The Short/Long-Term split captured here is informational (useful
  context for the accountant, and it's how IBKR/the US return sees it).
  It is NOT used to auto-select the Nispach C tax-rate column: Israeli
  capital-gains tax brackets for securities don't follow the US
  short/long holding-period distinction, so that classification is left
  for the accountant to confirm (see app/mapping/nispach_c.py).
"""

from __future__ import annotations

import io
import re
from datetime import date, datetime

import pdfplumber

from app.models.transactions import (
    Currency,
    Dividend,
    FeeItem,
    HoldingTerm,
    InterestItem,
    NormalizedStatement,
    SourceRef,
    Trade,
)

_NUM = r"-?[\d,]+\.\d{2}"
_DATE = r"\d{4}-\d{2}-\d{2}"

_PERIOD_RE = re.compile(
    r"([A-Za-z]+ \d{1,2}, \d{4}) - ([A-Za-z]+ \d{1,2}, \d{4})"
)
_BASE_CURRENCY_RE = re.compile(r"Base Currency\s+([A-Z]{3})")

_DIVIDEND_RE = re.compile(
    r"(?P<symbol>[A-Z][A-Z0-9.]*)\((?P<isin>[A-Z0-9]{6,12})\)\s+Cash Dividend\s+"
    r"(?P<ccy>[A-Z]{3})\s+(?P<rate>[\d.]+)\s+per\s+"
    r"(?:(?P<date1>" + _DATE + r")\s+(?P<amount1>" + _NUM + r")\s+)?"
    r"Share\s+"
    r"(?:(?P<date2>" + _DATE + r")\s+(?P<amount2>" + _NUM + r")\s+)?"
    r"\((?P<divtype>[^)]+)\)",
    re.DOTALL,
)

_DATED_AMOUNT_ROW_RE = re.compile(
    r"^(?P<date>" + _DATE + r")\s+(?P<desc>.+?)\s+(?P<amount>" + _NUM + r")$"
)

_SYMBOL_TOKEN_RE = re.compile(r"^[A-Z][A-Z0-9.]*$")
_SKIP_SYMBOLS = {"Total", "Stocks", "Forex", "Bonds", "Options", "Notes"}


def _flatten(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _parse_period(full_text: str) -> tuple[date, date]:
    m = _PERIOD_RE.search(full_text)
    if not m:
        raise ValueError(
            "לא זוהה טווח תאריכים בדוח (למשל 'January 1, 2025 - December 31, 2025'). "
            "ודאו שזהו קובץ Activity Statement תקין של Interactive Brokers."
        )
    start = datetime.strptime(m.group(1), "%B %d, %Y").date()
    end = datetime.strptime(m.group(2), "%B %d, %Y").date()
    return start, end


def _parse_base_currency(full_text: str) -> Currency:
    m = _BASE_CURRENCY_RE.search(full_text)
    if not m:
        raise ValueError(
            "לא נמצאה שורת 'Base Currency' בעמוד הראשון של הדוח. "
            "ודאו שזהו קובץ Activity Statement תקין של Interactive Brokers."
        )
    code = m.group(1)
    if code not in Currency.__members__:
        raise ValueError(
            f"מטבע הבסיס של החשבון הוא {code}, שאינו נתמך עדיין (רק USD נתמך ב-MVP הנוכחי). "
            "עיבוד חשבון שאינו דולרי דורש הרחבה של לוגיקת ההמרה - נא לפנות להרחבת המערכת לפני שימוש."
        )
    if code != "USD":
        raise ValueError(
            f"מטבע הבסיס של החשבון הוא {code}. גרסת ה-MVP הנוכחית תומכת רק בחשבונות דולריים (USD), "
            "כדי למנוע חישוב שגוי בשקט. נא לפנות להרחבת המערכת לתמיכה במטבע זה."
        )
    return Currency.USD


def _sanity_check_is_ibkr_statement(full_text: str) -> None:
    if "Interactive Brokers" not in full_text or "Activity Statement" not in full_text:
        raise ValueError(
            "הקובץ אינו נראה כמו Activity Statement של Interactive Brokers "
            "(לא נמצאו הכותרות הצפויות בעמוד הראשון)."
        )


def parse_dividends_text(text: str, statement_id: str, page: int) -> list[Dividend]:
    flat = _flatten(text)
    out: list[Dividend] = []
    for m in _DIVIDEND_RE.finditer(flat):
        date_str = m.group("date1") or m.group("date2")
        amount_str = m.group("amount1") or m.group("amount2")
        if not date_str or not amount_str:
            continue
        out.append(
            Dividend(
                pay_date=datetime.strptime(date_str, "%Y-%m-%d").date(),
                symbol=m.group("symbol"),
                isin=m.group("isin"),
                description=m.group("divtype"),
                gross_amount=float(amount_str.replace(",", "")),
                currency=Currency(m.group("ccy")) if m.group("ccy") in Currency.__members__ else Currency.USD,
                source=SourceRef(
                    statement_id=statement_id,
                    page=page,
                    table_name="Dividends",
                    row_text=m.group(0),
                ),
            )
        )
    return out


def _extract_block(text: str, start_header: str, end_marker: str = "Total") -> str | None:
    """Return the text between a line that == start_header and the next
    line starting with end_marker (inclusive of neither boundary line's
    surrounding noise beyond what's needed)."""
    lines = text.splitlines()
    try:
        start_idx = next(i for i, line in enumerate(lines) if line.strip() == start_header)
    except StopIteration:
        return None
    block_lines: list[str] = []
    for line in lines[start_idx + 1 :]:
        if line.strip().startswith(end_marker):
            break
        block_lines.append(line)
    return "\n".join(block_lines)


def parse_interest_text(text: str, statement_id: str, page: int) -> list[InterestItem]:
    block = _extract_block(text, "Interest")
    if not block:
        return []
    out: list[InterestItem] = []
    for line in block.splitlines():
        m = _DATED_AMOUNT_ROW_RE.match(line.strip())
        if not m:
            continue
        out.append(
            InterestItem(
                value_date=datetime.strptime(m.group("date"), "%Y-%m-%d").date(),
                description=m.group("desc").strip(),
                amount=float(m.group("amount").replace(",", "")),
                source=SourceRef(statement_id=statement_id, page=page, table_name="Interest", row_text=line.strip()),
            )
        )
    return out


def parse_fees_text(text: str, statement_id: str, page: int) -> list[FeeItem]:
    block = _extract_block(text, "Advisor Fees")
    if not block:
        return []
    out: list[FeeItem] = []
    for line in block.splitlines():
        m = _DATED_AMOUNT_ROW_RE.match(line.strip())
        if not m:
            continue
        out.append(
            FeeItem(
                description=m.group("desc").strip(),
                value_date=datetime.strptime(m.group("date"), "%Y-%m-%d").date(),
                amount=float(m.group("amount").replace(",", "")),
                source=SourceRef(statement_id=statement_id, page=page, table_name="Advisor Fees", row_text=line.strip()),
            )
        )
    return out


def parse_realized_pnl_text(text: str, statement_id: str, page: int, period_end: date) -> list[Trade]:
    """Parse rows of the 'Realized & Unrealized Performance Summary' table.

    Row shape (12 numeric columns after the symbol):
    Symbol  CostAdj  ST-Profit  ST-Loss  LT-Profit  LT-Loss  Total(realized)
            ST-Profit(unreal) ST-Loss(unreal) LT-Profit(unreal) LT-Loss(unreal) Total(unreal) Total(grand)
    We only need the realized columns (indices 1-4 after CostAdj, i.e. the
    2nd-5th numbers) plus the realized Total (6th number).
    """
    out: list[Trade] = []
    for line in text.splitlines():
        tokens = line.strip().split()
        if len(tokens) != 13:
            continue
        symbol = tokens[0]
        if symbol in _SKIP_SYMBOLS or not _SYMBOL_TOKEN_RE.match(symbol):
            continue
        try:
            nums = [float(t.replace(",", "")) for t in tokens[1:]]
        except ValueError:
            continue
        st_profit, st_loss, lt_profit, lt_loss = nums[1], nums[2], nums[3], nums[4]
        st_realized = st_profit + st_loss
        lt_realized = lt_profit + lt_loss
        if st_realized == 0 and lt_realized == 0:
            continue
        source = SourceRef(
            statement_id=statement_id,
            page=page,
            table_name="Realized & Unrealized Performance Summary",
            row_text=line.strip(),
        )
        if st_realized != 0:
            out.append(
                Trade(
                    symbol=symbol,
                    close_date=period_end,
                    proceeds=0.0,
                    cost_basis=0.0,
                    realized_pnl=round(st_realized, 2),
                    holding_term=HoldingTerm.SHORT,
                    source=source,
                )
            )
        if lt_realized != 0:
            out.append(
                Trade(
                    symbol=symbol,
                    close_date=period_end,
                    proceeds=0.0,
                    cost_basis=0.0,
                    realized_pnl=round(lt_realized, 2),
                    holding_term=HoldingTerm.LONG,
                    source=source,
                )
            )
    return out


_TOTAL_SYMBOL_LINE_RE = re.compile(
    r"^Total (?P<symbol>[A-Z][A-Z0-9.]*) (?P<qty>-?[\d,]+) (?P<proceeds>" + _NUM + r") "
    r"(?P<comm>" + _NUM + r") (?P<basis>" + _NUM + r") (?P<realized>" + _NUM + r") (?P<mtm>" + _NUM + r")$"
)


def parse_trade_totals_text(text: str) -> dict[str, float]:
    """Best-effort net sale proceeds per symbol from the Trades section's
    single-line 'Total <Symbol> ...' subtotal rows (see module docstring
    for why we don't reconstruct individual trade lots here)."""
    out: dict[str, float] = {}
    for line in text.splitlines():
        m = _TOTAL_SYMBOL_LINE_RE.match(line.strip())
        if not m:
            continue
        proceeds = float(m.group("proceeds").replace(",", ""))
        out[m.group("symbol")] = out.get(m.group("symbol"), 0.0) + proceeds
    return out


def _is_two_column_page(text: str) -> bool:
    has_dividends = "Dividends" in text
    has_side_column = any(h in text for h in ("Fees", "Interest Accruals", "Deposits & Withdrawals", "Interest\n"))
    return has_dividends and has_side_column


class IBKRActivityParser:
    broker_name = "IBKR"

    def parse(self, file_bytes: bytes, statement_id: str) -> NormalizedStatement:
        dividends: list[Dividend] = []
        interest: list[InterestItem] = []
        fees: list[FeeItem] = []
        trades: list[Trade] = []
        sale_proceeds_by_symbol: dict[str, float] = {}

        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            if not pdf.pages:
                raise ValueError("קובץ ה-PDF ריק (0 עמודים).")
            full_first_page = pdf.pages[0].extract_text() or ""
            _sanity_check_is_ibkr_statement(full_first_page)
            period_start, period_end = _parse_period(full_first_page)
            base_currency = _parse_base_currency(full_first_page)

            for i, page in enumerate(pdf.pages):
                page_num = i + 1
                text = page.extract_text() or ""

                if "Realized & Unrealized Performance Summary" in text:
                    trades.extend(parse_realized_pnl_text(text, statement_id, page_num, period_end))

                if re.search(r"^Trades$", text, re.MULTILINE):
                    for symbol, proceeds in parse_trade_totals_text(text).items():
                        sale_proceeds_by_symbol[symbol] = sale_proceeds_by_symbol.get(symbol, 0.0) + proceeds

                if "Dividends" in text:
                    if _is_two_column_page(text):
                        width = page.width
                        left_text = page.crop((0, 0, width / 2, page.height)).extract_text() or ""
                        right_text = page.crop((width / 2, 0, width, page.height)).extract_text() or ""
                        dividends.extend(parse_dividends_text(left_text, statement_id, page_num))
                        interest.extend(parse_interest_text(right_text, statement_id, page_num))
                        fees.extend(parse_fees_text(right_text, statement_id, page_num))
                    else:
                        dividends.extend(parse_dividends_text(text, statement_id, page_num))

        return NormalizedStatement(
            statement_id=statement_id,
            broker=self.broker_name,
            period_start=period_start,
            period_end=period_end,
            base_currency=base_currency,
            dividends=dividends,
            interest=interest,
            trades=trades,
            fees=fees,
            sale_proceeds_by_symbol=sale_proceeds_by_symbol,
        )
