"""Rebuilds per-lot capital-gain trades from individual executions.

Why: converting a gain to shekels at one rate is wrong for Israeli tax.
Cost and proceeds each have to be converted at the rate of their own
date (see mapping/capital_gain_fx.py), which needs each lot's open and
close dates -- data the statement's summary table does not carry but its
Trades table does.

Matching is FIFO per (account, symbol), including short sales (sold
first, bought back later). Every figure includes the execution's
commission, exactly as IBKR's own "Realized P/L" column does.

Guardrails (nothing is silently guessed):
- A closing execution that cannot be matched to an opening one in the
  statement (position opened in a prior year, or transferred in) becomes
  a lot with open_date=None and its cost taken from IBKR's own "Basis"
  column. It is flagged so the accountant can supply the acquisition date.
- Lots replace a symbol's summary-table trades only when their total
  reconciles to that summary total; otherwise the summary trade is kept
  and a warning is recorded.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from app.models.transactions import HoldingTerm, NormalizedStatement, Trade, TradeExecution

_RECONCILE_MIN_USD = 1.0
_RECONCILE_REL = 0.0001  # IBKR splits an execution's commission across the partial lots it closes
                         # in its own way, so a symbol with many partial lots drifts by a few dollars


@dataclass
class _OpenLot:
    open_date: object
    qty: float  # remaining, always positive
    sign: int  # +1 long, -1 short
    unit_cash: float  # cash per unit at open: negative for a purchase, positive for a short sale


def match_lots(executions: list[TradeExecution], statement_id: str) -> list[Trade]:
    by_key: dict[tuple[str | None, str], list[TradeExecution]] = defaultdict(list)
    for ex in executions:
        by_key[(ex.account, ex.symbol)].append(ex)

    lots: list[Trade] = []
    for (_account, _symbol), rows in by_key.items():
        rows = sorted(rows, key=lambda e: e.executed_on)  # stable: keeps statement order within a day
        queue: deque[_OpenLot] = deque()
        for ex in rows:
            qty = abs(ex.quantity)
            if qty == 0:
                continue
            sign = 1 if ex.quantity > 0 else -1
            net_cash = ex.proceeds + ex.commission  # a sale is positive, a purchase negative
            unit_cash = net_cash / qty

            remaining = qty
            while remaining > 1e-9 and queue and queue[0].sign == -sign:
                lot = queue[0]
                matched = min(remaining, lot.qty)
                open_cash = lot.unit_cash * matched
                close_cash = unit_cash * matched
                lots.append(_lot_trade(ex, open_cash, close_cash, lot.open_date, lot.sign < 0, statement_id))
                lot.qty -= matched
                remaining -= matched
                if lot.qty <= 1e-9:
                    queue.popleft()

            if remaining > 1e-9:
                if queue and queue[0].sign == sign:
                    queue.append(_OpenLot(ex.executed_on, remaining, sign, unit_cash))
                elif ex.code and "C" in ex.code.split(";")[0]:
                    # closes a position that is not visible in this statement:
                    # IBKR's Basis column is the cash of the lot(s) it closed
                    open_cash = ex.basis * (remaining / qty)
                    close_cash = unit_cash * remaining
                    lots.append(_lot_trade(ex, open_cash, close_cash, None, sign > 0, statement_id))
                else:
                    queue.append(_OpenLot(ex.executed_on, remaining, sign, unit_cash))
    return lots


def _lot_trade(
    closing: TradeExecution, open_cash: float, close_cash: float, open_date, is_short: bool, statement_id: str
) -> Trade:
    gain = open_cash + close_cash
    sell_cash = open_cash if is_short else close_cash
    buy_cash = close_cash if is_short else open_cash
    held_days = (closing.executed_on - open_date).days if open_date else None
    term = HoldingTerm.LONG if held_days is not None and held_days > 365 else HoldingTerm.SHORT
    note = None
    if open_date is None:
        note = "תאריך הרכישה אינו מופיע בדוח (פוזיציה שנפתחה בשנה קודמת או הועברה) - נדרש להזין תאריך רכישה."
    return Trade(
        symbol=closing.symbol,
        close_date=closing.executed_on,
        proceeds=round(sell_cash, 2),
        cost_basis=round(-buy_cash, 2),
        realized_pnl=round(gain, 2),
        holding_term=term,
        currency=closing.currency,
        source=closing.source,
        lot_level=True,
        open_date=open_date,
        is_short=is_short,
        note=note,
    )


def apply_lot_matching(statement: NormalizedStatement) -> NormalizedStatement:
    """Replace each symbol's summary-table trades with reconciled lots."""
    if not statement.executions:
        return statement

    lots = match_lots(statement.executions, statement.statement_id)
    lot_total: dict[str, float] = defaultdict(float)
    lot_gross: dict[str, float] = defaultdict(float)
    for lot in lots:
        lot_total[lot.symbol] += lot.realized_pnl
        lot_gross[lot.symbol] += abs(lot.realized_pnl)
    summary_total: dict[str, float] = defaultdict(float)
    for t in statement.trades:
        summary_total[t.symbol] += t.realized_pnl

    warnings = list(statement.warnings)
    replace: set[str] = set()
    for symbol, total in lot_total.items():
        if symbol not in summary_total:
            warnings.append(
                f"{symbol}: נמצאו עסקאות בטבלת Trades אך אין שורה בטבלת הרווח הממומש - נשמרו כלוטים (רווח ${total:,.2f}) לבדיקה."
            )
            replace.add(symbol)
        elif abs(total - summary_total[symbol]) <= max(_RECONCILE_MIN_USD, _RECONCILE_REL * lot_gross[symbol]):
            replace.add(symbol)
        else:
            warnings.append(
                f"{symbol}: סכום הלוטים שנבנו (${total:,.2f}) אינו תואם לרווח הממומש בדוח (${summary_total[symbol]:,.2f}) - "
                "נשמר החישוב לפי טבלת הסיכום (שער יום סוף התקופה) ודורש בדיקה ידנית."
            )

    kept = [t for t in statement.trades if t.symbol not in replace]
    new_trades = kept + [lot for lot in lots if lot.symbol in replace]
    return statement.model_copy(update={"trades": new_trades, "warnings": warnings})
