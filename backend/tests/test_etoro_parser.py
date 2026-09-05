"""Tests for the eToro XLSX parser.

These build a synthetic workbook using the column headers documented by
masbug/etoro-edavki (see app/parsers/etoro_statement.py docstring) --
they validate that our parsing *code* handles that documented shape
correctly. They do NOT prove the headers match a real eToro export,
since we don't have one to test against (unlike IBKR).
"""

import io
from datetime import date

import pytest
from openpyxl import Workbook

from app.parsers.etoro_statement import EToroStatementParser


def _build_workbook(
    dividend_rows: list[tuple],
    closed_position_rows: list[tuple],
    dividend_headers: list[str] | None = None,
    include_closed_positions_sheet: bool = True,
) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Dividends"
    ws.append(
        dividend_headers
        or [
            "Date of Payment",
            "Instrument Name",
            "Net Dividend Received (USD)",
            "Net Dividend Received (EUR)",
            "Withholding Tax Rate (%)",
            "Withholding Tax Amount (USD)",
            "Withholding Tax Amount (EUR)",
            "Position ID",
            "Type",
        ]
    )
    for row in dividend_rows:
        ws.append(row)

    if include_closed_positions_sheet:
        ws2 = wb.create_sheet("Closed Positions")
        ws2.append(
            [
                "Position ID",
                "Action",
                "Long / Short",
                "Amount",
                "Units / Contracts",
                "Open Date",
                "Close Date",
                "Leverage",
                "Spread Fees (USD)",
                "Market Spread (USD)",
                "Profit(USD)",
                "Profit(EUR)",
            ]
        )
        for row in closed_position_rows:
            ws2.append(row)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parses_dividends_with_gross_computed_from_net_plus_withholding():
    data = _build_workbook(
        dividend_rows=[
            ("01/03/2025 00:00:00", "Apple Inc", 42.5, 39.1, "15%", 7.5, 6.9, 1001, "Stock"),
        ],
        closed_position_rows=[],
    )
    stmt = EToroStatementParser().parse(data, "stmt-1")
    assert len(stmt.dividends) == 1
    d = stmt.dividends[0]
    assert d.symbol == "Apple Inc"
    assert d.pay_date == date(2025, 3, 1)
    assert d.withholding_tax == 7.5
    assert d.gross_amount == 50.0  # 42.5 net + 7.5 withheld


def test_parses_closed_positions_profit_as_realized_trade():
    data = _build_workbook(
        dividend_rows=[],
        closed_position_rows=[
            (2002, "Close BUY position", "Long", 1000, 10, "01/02/2025", "15/06/2025", 1, 0, 0, 123.45, 110.0),
        ],
    )
    stmt = EToroStatementParser().parse(data, "stmt-1")
    assert len(stmt.trades) == 1
    t = stmt.trades[0]
    assert t.symbol == "Position 2002"
    assert t.close_date == date(2025, 6, 15)
    assert t.realized_pnl == 123.45


def test_zero_profit_positions_are_skipped():
    data = _build_workbook(
        dividend_rows=[],
        closed_position_rows=[
            (2003, "Close BUY position", "Long", 500, 5, "01/02/2025", "15/06/2025", 1, 0, 0, 0.0, 0.0),
        ],
    )
    stmt = EToroStatementParser().parse(data, "stmt-1")
    assert len(stmt.trades) == 0


def test_header_matching_tolerates_whitespace_variants():
    # eToro's format versions use slightly different newline/spacing in headers
    # (e.g. "Amount\r\n in (USD)" vs "Amount (USD)", per etoro_statement's own
    # handling of this); our normalizer collapses any run of whitespace to a
    # single space so both variants resolve to the same lookup key.
    data = _build_workbook(
        dividend_rows=[("10/05/2025", "Microsoft Corp", 10.0, 9.2, "10%", 1.0, 0.9, 3003, "Stock")],
        closed_position_rows=[],
        dividend_headers=[
            "Date \n of \r\n Payment",
            "Instrument Name",
            "Net Dividend Received (USD)",
            "Net Dividend Received (EUR)",
            "Withholding Tax Rate (%)",
            "Withholding Tax Amount (USD)",
            "Withholding Tax Amount (EUR)",
            "Position ID",
            "Type",
        ],
    )
    stmt = EToroStatementParser().parse(data, "stmt-1")
    assert len(stmt.dividends) == 1
    assert stmt.dividends[0].symbol == "Microsoft Corp"


def test_rejects_workbook_missing_required_sheets():
    wb = Workbook()
    ws = wb.active
    ws.title = "SomeOtherSheet"
    ws.append(["A", "B"])
    buf = io.BytesIO()
    wb.save(buf)

    with pytest.raises(ValueError, match="לשוניות"):
        EToroStatementParser().parse(buf.getvalue(), "stmt-1")


def test_rejects_non_xlsx_bytes():
    with pytest.raises(ValueError):
        EToroStatementParser().parse(b"not an excel file", "stmt-1")
