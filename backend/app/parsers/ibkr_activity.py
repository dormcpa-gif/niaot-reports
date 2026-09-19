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

- Capital gains have two sources. The "Realized & Unrealized Performance
  Summary" table gives one clean line per symbol (realized S/T and L/T
  already split) and is the authority for each symbol's total. The raw
  "Trades" table gives every execution with its date; its rows wrap
  (date on the line above, sometimes the price too), so they are only
  accepted right after a date line -- see parse_trade_executions_text.
  services/lot_matching.py rebuilds per-lot trades from the executions
  and uses them for a symbol only when they reconcile to the summary total.

- The Short/Long-Term split captured here is informational (useful
  context for the accountant, and it's how IBKR/the US return sees it).
  It is NOT used to auto-select the Nispach C tax-rate column: Israeli
  capital-gains tax brackets for securities don't follow the US
  short/long holding-period distinction, so that classification is left
  for the accountant to confirm (see app/mapping/nispach_c.py).

- IBKR (U.K.) Limited / Central Europe accounts use this exact same
  Activity Statement layout, just with a GBP or EUR base currency
  instead of USD (confirmed only by inspecting the format of the real
  US statement we validated against, which references "Interactive
  Brokers (U.K.) Limited" as a clearing entity on the same template --
  **not yet run against a real GBP/EUR statement**, so treat non-USD
  results with the same extra scrutiny as the eToro parser). Any other
  base currency is still rejected explicitly rather than silently
  mis-converted, since currency_service needs a matching FX rate table.

- "Custom Consolidated" statements (one PDF spanning several IBKR
  sub-accounts, e.g. Account "U1234567 (Custom Consolidated)",
  Accounts Included "U7654321, U1234567") validated against a second
  real statement -- these prefix every dated row with the sub-account
  id (e.g. "U1234567 2025-03-03 2,760.00"), and pair different sections
  side-by-side than a single-account statement does (Withholding Tax +
  Dividends on one page; Interest + a section literally called "Other
  Fees", not "Advisor Fees", on another -- see _is_two_column_page).
  Sub-account attribution itself is discarded (all rows are merged into
  one statement, same as the existing per-symbol aggregation) since
  NormalizedStatement has no per-sub-account field. Known residual gap:
  a row whose description wraps across three lines with the amount
  alone on the middle line (no description text next to it, e.g. a
  "...SYEP Interest for Feb-\n<account> <date> <amount>\n2025" split)
  is correctly skipped rather than mis-parsed -- confirmed via a small
  (~2%) shortfall against that statement's own printed interest total.
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
    TradeExecution,
    SourceRef,
    Trade,
)

_NUM = r"-?[\d,]+\.\d{2}"
_DATE = r"\d{4}-\d{2}-\d{2}"

_PERIOD_RE = re.compile(
    r"([A-Za-z]+ \d{1,2}, \d{4}) - ([A-Za-z]+ \d{1,2}, \d{4})"
)
_BASE_CURRENCY_RE = re.compile(r"Base Currency\s+([A-Z]{3})")

# A "Custom Consolidated" statement spanning multiple sub-accounts (see
# module docstring) prefixes each dated amount with the sub-account id
# (e.g. "U1234567") that row belongs to -- optional here so the same
# regex handles both a single-account and a consolidated statement.
_ACCOUNT_PREFIX = r"(?:[A-Z]\d{6,9}\s+)?"

_DIVIDEND_RE = re.compile(
    r"(?P<symbol>[A-Z][A-Z0-9.]*)\((?P<isin>[A-Z0-9]{6,12})\)\s+Cash Dividend\s+"
    r"(?P<ccy>[A-Z]{3})\s+(?P<rate>[\d.]+)\s+per\s+"
    r"(?:" + _ACCOUNT_PREFIX + r"(?P<date1>" + _DATE + r")\s+(?P<amount1>" + _NUM + r")\s+)?"
    r"Share\s+"
    r"(?:" + _ACCOUNT_PREFIX + r"(?P<date2>" + _DATE + r")\s+(?P<amount2>" + _NUM + r")\s+)?"
    r"\((?P<divtype>[^)]+)\)",
    re.DOTALL,
)

_DATED_AMOUNT_ROW_RE = re.compile(
    r"^" + _ACCOUNT_PREFIX + r"(?P<date>" + _DATE + r")\s+(?P<desc>.+?)\s+(?P<amount>" + _NUM + r")$"
)

# "Payment in Lieu of Dividend" (paid by a share borrower when the
# lender's shares are on loan over an ex-dividend date, instead of an
# actual dividend from the issuer) has no per-share CCY/rate portion at
# all, unlike _DIVIDEND_RE above -- a structurally different row, not a
# wrapping variant of the same one. Still real, taxable substitute
# income though, so it's captured here (tagged in its description as a
# substitute payment, not an actual dividend, for the accountant to
# characterize correctly rather than silently treating it as identical).
_PAYMENT_IN_LIEU_RE = re.compile(
    r"(?P<symbol>[A-Z][A-Z0-9.]*)\((?P<isin>[A-Z0-9]{6,12})\)\s+Payment in Lieu of Dividend\s+"
    r"" + _ACCOUNT_PREFIX + r"(?P<date>" + _DATE + r")\s+(?P<amount>" + _NUM + r")\s+"
    r"\((?P<divtype>[^)]+)\)",
    re.DOTALL,
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


_SUPPORTED_BASE_CURRENCIES = {"USD", "GBP", "EUR"}


def _parse_base_currency(full_text: str) -> Currency:
    """USD covers IBKR (US); GBP/EUR cover IBKR (U.K.) Limited /
    Central Europe accounts, which use the identical statement layout
    (see module docstring in the broker-support README section) -- only
    the base currency and per-row currency codes differ. Any other
    currency is rejected explicitly rather than silently mis-converted,
    since currency_service has no rate table for it by default."""
    m = _BASE_CURRENCY_RE.search(full_text)
    if not m:
        raise ValueError(
            "לא נמצאה שורת 'Base Currency' בעמוד הראשון של הדוח. "
            "ודאו שזהו קובץ Activity Statement תקין של Interactive Brokers."
        )
    code = m.group(1)
    if code not in _SUPPORTED_BASE_CURRENCIES or code not in Currency.__members__:
        raise ValueError(
            f"מטבע הבסיס של החשבון הוא {code}, שאינו נתמך עדיין (USD/GBP/EUR בלבד נתמכים כרגע). "
            "עיבוד חשבון במטבע אחר דורש הרחבה של לוגיקת ההמרה - נא לפנות להרחבת המערכת לפני שימוש."
        )
    return Currency(code)


def _sanity_check_is_ibkr_statement(full_text: str) -> None:
    if "Interactive Brokers" not in full_text or "Activity Statement" not in full_text:
        raise ValueError(
            "הקובץ אינו נראה כמו Activity Statement של Interactive Brokers "
            "(לא נמצאו הכותרות הצפויות בעמוד הראשון)."
        )


_EMBEDDED_DATE_AMOUNT_RE = re.compile(_ACCOUNT_PREFIX + r"(" + _DATE + r")\s+(" + _NUM + r")")


def parse_dividends_text(
    text: str, statement_id: str, page: int, default_currency: Currency = Currency.USD
) -> list[Dividend]:
    flat = _flatten(text)
    out: list[Dividend] = []
    for m in _DIVIDEND_RE.finditer(flat):
        date_str = m.group("date1") or m.group("date2")
        amount_str = m.group("amount1") or m.group("amount2")
        divtype = m.group("divtype")
        if not date_str or not amount_str:
            # A multi-word divtype (e.g. "Bonus Dividend") can wrap onto
            # its own line in the source PDF, landing the date/amount
            # token *inside* this capture once flattened (e.g. "(Bonus
            # U1234567 2025-03-03 2,760.00 Dividend)") instead of before
            # it -- recover them from there rather than dropping the row.
            embedded = _EMBEDDED_DATE_AMOUNT_RE.search(divtype)
            if not embedded:
                continue
            date_str, amount_str = embedded.group(1), embedded.group(2)
            divtype = _flatten(divtype[: embedded.start()] + " " + divtype[embedded.end() :])
        out.append(
            Dividend(
                pay_date=datetime.strptime(date_str, "%Y-%m-%d").date(),
                symbol=m.group("symbol"),
                isin=m.group("isin"),
                description=divtype,
                gross_amount=float(amount_str.replace(",", "")),
                currency=Currency(m.group("ccy")) if m.group("ccy") in Currency.__members__ else default_currency,
                source=SourceRef(
                    statement_id=statement_id,
                    page=page,
                    table_name="Dividends",
                    row_text=m.group(0),
                ),
            )
        )

    for m in _PAYMENT_IN_LIEU_RE.finditer(flat):
        out.append(
            Dividend(
                pay_date=datetime.strptime(m.group("date"), "%Y-%m-%d").date(),
                symbol=m.group("symbol"),
                isin=m.group("isin"),
                description=f"Payment in Lieu of Dividend ({m.group('divtype')}) -- תשלום תחליפי, לא דיבידנד ישירות מהמנפיק (המניה הייתה מושאלת)",
                gross_amount=float(m.group("amount").replace(",", "")),
                currency=default_currency,
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


def parse_interest_text(
    text: str, statement_id: str, page: int, currency: Currency = Currency.USD
) -> list[InterestItem]:
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
                currency=currency,
                source=SourceRef(statement_id=statement_id, page=page, table_name="Interest", row_text=line.strip()),
            )
        )
    return out


def parse_fees_text(text: str, statement_id: str, page: int, currency: Currency = Currency.USD) -> list[FeeItem]:
    """Recognizes both "Advisor Fees" (a fixed advisory/AUM fee, seen on
    single-account statements) and "Other Fees" (exposure fees, borrow
    fees, class-action/snapshot fees etc., seen on "Custom Consolidated"
    multi-sub-account statements instead) -- different real fee
    categories IBKR uses depending on account setup, not a naming
    inconsistency to normalize away; table_name below reflects which one
    actually matched."""
    for header in ("Advisor Fees", "Other Fees"):
        block = _extract_block(text, header)
        if block:
            break
    else:
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
                currency=currency,
                source=SourceRef(statement_id=statement_id, page=page, table_name=header, row_text=line.strip()),
            )
        )
    return out


def parse_realized_pnl_text(
    text: str, statement_id: str, page: int, period_end: date, currency: Currency = Currency.USD
) -> list[Trade]:
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
                    currency=currency,
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
                    currency=currency,
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


# A long trade price wraps: "2025-06-17, 698.78093333" then the row without its price column.
_EXEC_DATE_LINE_RE = re.compile(r"^(" + _DATE + r"),\s*(?P<price>-?[\d,]*\.\d+)?")
_EXEC_ROW_RE = re.compile(
    r"^(?:(?P<account>[A-Z]\d{6,9})\s+)?(?P<symbol>[A-Z][A-Z0-9.]*)\s+"
    r"(?P<qty>-?[\d,]+(?:\.\d+)?)\s+(?:(?P<price>-?[\d,]*\.\d+)\s+)?(?P<cprice>-?[\d,]*\.\d+)\s+"
    r"(?P<proceeds>" + _NUM + r")\s+(?P<comm>" + _NUM + r")\s+(?P<basis>" + _NUM + r")\s+"
    r"(?P<realized>" + _NUM + r")\s+(?P<mtm>" + _NUM + r")(?:\s+(?P<code>[A-Z;]+))?$"
)


def parse_trade_executions_text(
    text: str, statement_id: str, page: int, currency: Currency = Currency.USD
) -> list[TradeExecution]:
    """Parse individual rows of the Trades table.

    In the PDF text each execution is split over lines: the date on the
    line before the row ("2025-09-24,"), the time on the line after. A
    row is only accepted when the line right before it is such a date
    line, which keeps look-alike rows elsewhere (positions, totals) out.
    Rows with a different column layout (Forex, options) simply do not
    match and are left to the summary-table path -- lot matching checks
    every symbol against the statement's own realized totals, so a
    silently skipped row shows up as a reconciliation warning.
    """
    out: list[TradeExecution] = []
    pending_date: date | None = None
    pending_price: float | None = None
    for raw in text.splitlines():
        line = raw.strip()
        d = _EXEC_DATE_LINE_RE.match(line)
        if d:
            pending_date = date.fromisoformat(d.group(1))
            pending_price = float(d.group("price").replace(",", "")) if d.group("price") else None
            continue
        if pending_date is None:
            continue
        m = _EXEC_ROW_RE.match(line)
        if not m:
            if not re.match(r"^\d{2}:\d{2}:\d{2}$", line):
                pending_date = None
            continue
        out.append(
            TradeExecution(
                account=m.group("account"),
                symbol=m.group("symbol"),
                executed_on=pending_date,
                quantity=float(m.group("qty").replace(",", "")),
                price=float(m.group("price").replace(",", "")) if m.group("price") else (pending_price or 0.0),
                proceeds=float(m.group("proceeds").replace(",", "")),
                commission=float(m.group("comm").replace(",", "")),
                basis=float(m.group("basis").replace(",", "")),
                realized_pnl=float(m.group("realized").replace(",", "")),
                code=m.group("code"),
                currency=currency,
                source=SourceRef(statement_id=statement_id, page=page, table_name="Trades", row_text=line),
            )
        )
        pending_date = None
    return out


def _is_two_column_page(text: str) -> bool:
    """True for any page laid out as two side-by-side statement
    sections. Which two sections varies:
      - single-account statements: Dividends (left) + Fees/Interest (right)
      - "Custom Consolidated" multi-sub-account statements (see module
        docstring): Withholding Tax (left) + Dividends (right) on one
        page, and separately Interest (left) + Fees (right) on another,
        with no "Dividends" on that second kind of page at all.
    Rather than hard-code which section is on which side (fragile, and
    wrong here -- see below), the caller tries every extractor against
    both crops and keeps whatever each one actually matches."""
    has_dividends = "Dividends" in text
    has_side_column = any(h in text for h in ("Fees", "Interest Accruals", "Deposits & Withdrawals", "Interest\n"))
    has_interest_and_fees = "Interest" in text and "Fees" in text
    return (has_dividends and has_side_column) or has_interest_and_fees


class IBKRActivityParser:
    broker_name = "IBKR"

    def parse(self, file_bytes: bytes, statement_id: str) -> NormalizedStatement:
        dividends: list[Dividend] = []
        interest: list[InterestItem] = []
        fees: list[FeeItem] = []
        trades: list[Trade] = []
        executions: list[TradeExecution] = []
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
                    trades.extend(parse_realized_pnl_text(text, statement_id, page_num, period_end, base_currency))

                executions.extend(parse_trade_executions_text(text, statement_id, page_num, base_currency))

                if re.search(r"^Trades$", text, re.MULTILINE):
                    for symbol, proceeds in parse_trade_totals_text(text).items():
                        sale_proceeds_by_symbol[symbol] = sale_proceeds_by_symbol.get(symbol, 0.0) + proceeds

                if _is_two_column_page(text):
                    # Try every extractor against both halves instead of
                    # assuming which side holds which section (see
                    # _is_two_column_page docstring) -- each extractor's
                    # own header/regex match is specific enough to come
                    # back empty on the wrong half, so this is safe and
                    # handles whichever pairing this page actually has.
                    width = page.width
                    left_text = page.crop((0, 0, width / 2, page.height)).extract_text() or ""
                    right_text = page.crop((width / 2, 0, width, page.height)).extract_text() or ""
                    for half in (left_text, right_text):
                        dividends.extend(parse_dividends_text(half, statement_id, page_num, base_currency))
                        interest.extend(parse_interest_text(half, statement_id, page_num, base_currency))
                        fees.extend(parse_fees_text(half, statement_id, page_num, base_currency))
                elif "Dividends" in text:
                    dividends.extend(parse_dividends_text(text, statement_id, page_num, base_currency))

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
            executions=executions,
        )
