"""Unit tests for the text-level IBKR parsing functions.

These test the regex/line-parsing logic directly against known-shape
text blocks (mirroring the real IBKR Activity Statement layout we
verified the parser against), without needing a PDF fixture. This keeps
the suite fast and avoids checking any real client data into the repo.
"""

from datetime import date

from app.parsers.ibkr_activity import (
    parse_dividends_text,
    parse_fees_text,
    parse_interest_text,
    parse_realized_pnl_text,
    parse_trade_totals_text,
)

DIVIDENDS_BLOCK = """
Dividends
Date Description Amount
USD
MINT(US72201R8337) Cash Dividend USD 0.40 per Share
2025-01-03 51.20
(Ordinary Dividend)
VCSH(US92206C4096) Cash Dividend USD 0.28130032 per
2025-02-05 23.35
Share (Ordinary Dividend)
"""

INTEREST_BLOCK = """
Interest
Date Description Amount
USD
2025-10-03 USD Debit Interest for Sep-2025 -1.82
Total -1.82
"""

FEES_BLOCK = """
Fees
Date Description Amount
Advisor Fees
USD
2025-01-02 FA Fee: Percent of Equity, Posted Quarterly -615.43
2025-04-01 FA Fee: Percent of Equity, Posted Quarterly -320.92
Total -936.35
"""

REALIZED_UNREALIZED_BLOCK = """
Realized & Unrealized Performance Summary
Realized Unrealized
Symbol Cost Adj. S/T Profit S/T Loss L/T Profit L/T Loss Total S/T Profit S/T Loss L/T Profit L/T Loss Total Total Code
Stocks
BSJP 0.00 0.00 0.00 6.13 0.00 6.13 0.00 0.00 0.00 0.00 0.00 6.13
QQQ 0.00 0.00 0.00 6,424.46 0.00 6,424.46 573.83 -65.65 4,164.98 0.00 4,673.16 11,097.63
FDN 0.00 2,318.28 0.00 0.00 0.00 2,318.28 0.00 0.00 0.00 0.00 0.00 2,318.28
Total Stocks 0.00 8,742.74 0.00 6,430.59 0.00 15,173.33 573.83 -65.65 4,164.98 0.00 4,673.16 19,846.49
"""

TRADE_TOTALS_BLOCK = """
Trades
Symbol Date/Time Quantity T. Price C. Price Proceeds Comm/Fee Basis Realized P/L MTM P/L Code
Total BSJP -438 10,092.83 -3.07 -10,083.64 6.13 1.31
Total BSJQ 433 -10,112.72 -3.03 10,115.75 0.00 -6.50
"""


def test_parse_dividends_handles_both_wrap_positions():
    result = parse_dividends_text(DIVIDENDS_BLOCK, "stmt-1", page=7)
    assert len(result) == 2

    mint = next(d for d in result if d.symbol == "MINT")
    assert mint.isin == "US72201R8337"
    assert mint.pay_date == date(2025, 1, 3)
    assert mint.gross_amount == 51.20
    assert mint.description == "Ordinary Dividend"

    vcsh = next(d for d in result if d.symbol == "VCSH")
    assert vcsh.pay_date == date(2025, 2, 5)
    assert vcsh.gross_amount == 23.35


def test_parse_interest_text():
    result = parse_interest_text(INTEREST_BLOCK, "stmt-1", page=7)
    assert len(result) == 1
    assert result[0].amount == -1.82
    assert result[0].value_date == date(2025, 10, 3)


def test_parse_fees_text():
    result = parse_fees_text(FEES_BLOCK, "stmt-1", page=7)
    assert len(result) == 2
    assert round(sum(f.amount for f in result), 2) == -936.35


def test_parse_realized_pnl_splits_short_and_long_term():
    trades = parse_realized_pnl_text(REALIZED_UNREALIZED_BLOCK, "stmt-1", page=2, period_end=date(2025, 12, 31))
    # BSJP: long-term only (6.13); QQQ: long-term only (6424.46); FDN: short-term only (2318.28)
    by_symbol = {(t.symbol, t.holding_term.value): t.realized_pnl for t in trades}
    assert by_symbol[("BSJP", "long")] == 6.13
    assert by_symbol[("QQQ", "long")] == 6424.46
    assert by_symbol[("FDN", "short")] == 2318.28
    # the "Total Stocks" aggregate row must NOT produce a Trade record
    assert all(t.symbol != "Stocks" for t in trades)


def test_parse_trade_totals_text():
    totals = parse_trade_totals_text(TRADE_TOTALS_BLOCK)
    assert totals["BSJP"] == 10092.83
    assert totals["BSJQ"] == -10112.72
