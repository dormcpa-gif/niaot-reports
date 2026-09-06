"""Unit tests for the text-level Schedule K-1 box-extraction logic.

These test the regex/line-parsing logic directly against text blocks
shaped like the K-1's official box labels (see
app/parsers/k1_schedule.py docstring for why we test at this level
instead of against a real K-1 PDF, which we don't have).
"""

import pytest

from app.parsers.k1_schedule import (
    _find_box_amount,
    _find_tax_year,
    _sanity_check_is_k1,
)

K1_TEXT = """
Schedule K-1 (Form 1065) 2025
Part III Partner's Share of Current Year Income, Deductions, Credits, and Other Items
5 Interest income 1,234.56
6a Ordinary dividends 789.10
6b Qualified dividends 700.00
8 Net short-term capital gain (loss) 250.00
9a Net long-term capital gain (loss) 5,000.00
"""


def test_finds_interest_and_dividend_boxes():
    assert _find_box_amount(K1_TEXT, "5 Interest income") == 1234.56
    assert _find_box_amount(K1_TEXT, "6a Ordinary dividends") == 789.10


def test_finds_capital_gain_boxes():
    assert _find_box_amount(K1_TEXT, "8 Net short-term capital gain") == 250.00
    assert _find_box_amount(K1_TEXT, "9a Net long-term capital gain") == 5000.00


def test_missing_box_returns_none_instead_of_guessing():
    assert _find_box_amount(K1_TEXT, "11 Other income") is None


def test_finds_tax_year():
    assert _find_tax_year(K1_TEXT) == 2025


def test_sanity_check_rejects_unrelated_document():
    with pytest.raises(ValueError, match="Schedule K-1"):
        _sanity_check_is_k1("Some unrelated PDF content")


def test_sanity_check_accepts_k1_header():
    _sanity_check_is_k1("Schedule K-1 (Form 1065) 2025")
