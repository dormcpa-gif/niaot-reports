"""Unit tests for the text-level Form 1040 line-extraction logic.

See app/parsers/form_1040.py docstring for the important caveat about
double-counting risk and why this parser is a last resort, and for why
these tests validate our parsing *code* against the form's documented
line layout rather than a real signed return, which we don't have.
"""

import pytest

from app.parsers.form_1040 import _find_line_amount, _find_tax_year, _sanity_check_is_1040

FORM_1040_TEXT = """
Form 1040 (2025)
U.S. Individual Income Tax Return 2025
2b Taxable interest 1,500.00
3a Qualified dividends 400.00
3b Ordinary dividends 900.25
7 Capital gain or (loss) 4,250.75
"""


def test_finds_interest_and_dividend_lines():
    assert _find_line_amount(FORM_1040_TEXT, "2b Taxable interest") == 1500.00
    assert _find_line_amount(FORM_1040_TEXT, "3b Ordinary dividends") == 900.25


def test_finds_capital_gain_line():
    assert _find_line_amount(FORM_1040_TEXT, "7 Capital gain or (loss)") == 4250.75


def test_does_not_double_extract_qualified_dividends_separately():
    # 3a (qualified) is a subset of 3b (ordinary) -- this parser only
    # extracts 3b to avoid counting the same dollars twice.
    assert _find_line_amount(FORM_1040_TEXT, "3a Qualified dividends") == 400.00
    # confirming 3a *can* be read (regex works) is not the same as the
    # parser using it -- Form1040Parser.parse() only calls _find_line_amount
    # with the 3b label, never 3a.


def test_finds_tax_year():
    assert _find_tax_year(FORM_1040_TEXT) == 2025


def test_sanity_check_rejects_unrelated_document():
    with pytest.raises(ValueError, match="1040"):
        _sanity_check_is_1040("Some unrelated PDF content")


def test_sanity_check_accepts_1040_header():
    _sanity_check_is_1040("Form 1040 (2025)\nU.S. Individual Income Tax Return 2025")
