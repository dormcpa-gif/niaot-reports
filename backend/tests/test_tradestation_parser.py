"""Tests for the TradeStation CSV export parser.

These validate our parsing *code* against the generic column layout
TradeStation's own documentation describes (see
app/parsers/tradestation_export.py docstring). They do NOT prove these
headers match a real TradeStation export, since we don't have one to
test against (unlike IBKR) and couldn't find a live open-source
reference the way we did for eToro -- treat results with extra scrutiny.
"""

from datetime import date

import pytest

from app.parsers.tradestation_export import TradeStationExportParser

GAIN_LOSS_CSV = (
    "Symbol,Description,Quantity,Date Acquired,Date Sold,Proceeds,Cost Basis,"
    "Wash Sale Loss Disallowed,Gain/Loss,Term\n"
    "AAPL,Apple Inc,100,01/10/2024,03/15/2025,15000.00,12000.00,0.00,3000.00,Long\n"
    "TSLA,Tesla Inc,50,11/01/2024,12/15/2025,9000.00,9500.00,0.00,-500.00,Short\n"
)

CASH_ACTIVITY_CSV = (
    "Date,Description,Amount,Type\n"
    "01/15/2025,AAPL Dividend,42.50,Dividend\n"
    "02/01/2025,Credit Interest,3.10,Credit Interest\n"
)


def test_parses_gain_loss_export_into_trades():
    stmt = TradeStationExportParser().parse(GAIN_LOSS_CSV.encode("utf-8"), "stmt-1")
    assert len(stmt.trades) == 2
    aapl = next(t for t in stmt.trades if t.symbol == "AAPL")
    assert aapl.close_date == date(2025, 3, 15)
    assert aapl.realized_pnl == 3000.00
    assert aapl.holding_term.value == "long"

    tsla = next(t for t in stmt.trades if t.symbol == "TSLA")
    assert tsla.holding_term.value == "short"
    assert tsla.realized_pnl == -500.00


def test_parses_cash_activity_export_into_dividends_and_interest():
    stmt = TradeStationExportParser().parse(CASH_ACTIVITY_CSV.encode("utf-8"), "stmt-1")
    assert len(stmt.dividends) == 1
    assert stmt.dividends[0].symbol == "AAPL"
    assert stmt.dividends[0].gross_amount == 42.50

    assert len(stmt.interest) == 1
    assert stmt.interest[0].amount == 3.10


def test_rejects_csv_with_unrecognized_headers():
    with pytest.raises(ValueError, match="לא זוהו כותרות"):
        TradeStationExportParser().parse(b"Foo,Bar\n1,2\n", "stmt-1")


def test_rejects_non_csv_bytes():
    with pytest.raises(ValueError):
        TradeStationExportParser().parse(b"\xff\xfe not valid utf8 \x00\x01", "stmt-1")
