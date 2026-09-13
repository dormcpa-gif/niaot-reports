"""Unit tests for the text-level Form 1040 line-extraction logic.

See app/parsers/form_1040.py docstring for the important caveat about
double-counting risk and why this parser is a last resort. The block
below mirrors the ACTUAL text layout pdfplumber extracted from a real,
professionally-prepared 1040 (tax-prep software output) that this
parser was validated against -- notably: line-number prefixes ("2b",
"3b"...) are not adjacent to their description text, amounts are
preceded by a run of "~" leader characters, a single line can carry two
labels' worth of value ("Qualified dividends ~~~~ 1,556. Ordinary
dividends ~~~~~ 6,472."), and a filled whole-dollar amount can have zero
digits after the decimal point ("6,472." not "6,472.00"). A blank/zero
line for this same real filer (interest) has no trailing number at all.
"""

import pytest

from app.parsers.form_1040 import _find_line_amount, _find_tax_year, _sanity_check_is_1040

REAL_LAYOUT_PAGE = """
mroF 1040 2025
U.S. Individual Income Tax Return
For the year Jan. 1 - Dec. 31, 2025, or other tax year beginning , ending
Add lines 1a through 1h~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ 34,361.
Attach Sch. B Tax-exempt interest ~~~ Taxable interest ~~~~~~
Qualified dividends ~~~~ 1,556. Ordinary dividends ~~~~~ 6,472.
Capital gain or (loss). Attach Schedule D if required ~~~~~~~~~~~~~~~~~~~~~ 45,277.
"""


def test_finds_ordinary_dividends_even_though_qualified_dividends_precedes_it_on_the_same_line():
    result = _find_line_amount([REAL_LAYOUT_PAGE], "Ordinary dividends")
    assert result is not None
    amount, page_num, row_text = result
    assert amount == 6472.0
    assert page_num == 1
    assert "Qualified dividends" in row_text  # confirms it's the shared line, not a hallucinated one


def test_finds_capital_gain_despite_extra_words_between_label_and_amount():
    result = _find_line_amount([REAL_LAYOUT_PAGE], "Capital gain or (loss)")
    assert result is not None
    amount, _, _ = result
    assert amount == 45277.0


def test_blank_interest_line_yields_no_match_instead_of_a_wrong_number():
    # This real filer had $0 taxable interest -- the line has no trailing
    # amount at all after "Taxable interest", and must not be confused
    # with a neighboring number from elsewhere on the line/page.
    assert _find_line_amount([REAL_LAYOUT_PAGE], "Taxable interest") is None


def test_whole_dollar_amount_with_no_cents_digits_parses_correctly():
    # "34,361." (trailing period, zero digits after it) must not crash
    # or silently parse as e.g. 34361.0 -> confirmed via a dedicated label
    result = _find_line_amount([REAL_LAYOUT_PAGE], "Add lines 1a through 1h")
    assert result is not None
    amount, _, _ = result
    assert amount == 34361.0


def test_finds_tax_year_from_the_real_layouts_year_range_line():
    assert _find_tax_year(REAL_LAYOUT_PAGE) == 2025


def test_amount_is_attributed_to_the_correct_page_number():
    pages = ["no relevant lines here", REAL_LAYOUT_PAGE, "also nothing here"]
    result = _find_line_amount(pages, "Ordinary dividends")
    assert result is not None
    _, page_num, _ = result
    assert page_num == 2


def test_sanity_check_rejects_unrelated_document():
    with pytest.raises(ValueError, match="1040"):
        _sanity_check_is_1040("Some unrelated PDF content")


def test_sanity_check_accepts_1040_header():
    _sanity_check_is_1040("Form 1040 (2025)\nU.S. Individual Income Tax Return 2025")
