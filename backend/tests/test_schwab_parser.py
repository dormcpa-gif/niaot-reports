"""Unit tests for the text-level Schwab/TD Ameritrade parsing logic.

These test the regex/line-parsing logic directly against text blocks
built from the layout documented in Schwab's public statement guide
(see app/parsers/schwab_statement.py docstring) -- they validate our
parsing *code* against that documented shape, not against a real
Schwab statement, which we don't have. Treat with extra scrutiny.
"""

from datetime import date

import pytest

from app.parsers.schwab_statement import (
    _parse_period,
    _sanity_check_is_schwab_statement,
    parse_transactions_text,
)

TRANSACTIONS_BLOCK = """
Date Category Action Symbol Description Quantity Price Amount
01/15/2025 Dividends & Interest Qualified Dividend AAPL APPLE INC 42.50
02/01/2025 Dividends & Interest Bank Interest Schwab Bank Interest 3.10
"""


def test_parses_dividend_and_interest_rows():
    dividends, interest = parse_transactions_text(TRANSACTIONS_BLOCK, "stmt-1", page=1)
    assert len(dividends) == 1
    assert dividends[0].symbol == "AAPL"
    assert dividends[0].gross_amount == 42.50
    assert dividends[0].pay_date == date(2025, 1, 15)

    assert len(interest) == 1
    assert interest[0].amount == 3.10
    assert interest[0].value_date == date(2025, 2, 1)


def test_sanity_check_rejects_unrelated_document():
    with pytest.raises(ValueError, match="Schwab"):
        _sanity_check_is_schwab_statement("Some unrelated PDF content")


def test_sanity_check_accepts_td_ameritrade_too():
    _sanity_check_is_schwab_statement("TD Ameritrade Brokerage Statement")


def test_parses_period_from_statement_period_line():
    start, end = _parse_period("Statement Period 01/01/2025 - 12/31/2025")
    assert start == date(2025, 1, 1)
    assert end == date(2025, 12, 31)
