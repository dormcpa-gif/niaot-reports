"""Tests for the robustness guardrails added on top of the base parser:
rejecting non-IBKR PDFs and non-USD accounts with a clear error instead
of silently producing wrong/empty data."""

import pytest

from app.parsers.ibkr_activity import (
    _parse_base_currency,
    _parse_period,
    _sanity_check_is_ibkr_statement,
)

VALID_HEADER = """
Activity Statement
January 1, 2025 - December 31, 2025
Interactive Brokers LLC, Two Pickwick Plaza, Greenwich, CT 06830
Account Information
Name Test Client
Base Currency USD
"""


def test_valid_header_parses_cleanly():
    _sanity_check_is_ibkr_statement(VALID_HEADER)
    start, end = _parse_period(VALID_HEADER)
    assert start.isoformat() == "2025-01-01"
    assert end.isoformat() == "2025-12-31"
    assert _parse_base_currency(VALID_HEADER).value == "USD"


def test_rejects_a_document_that_is_not_an_ibkr_statement():
    with pytest.raises(ValueError, match="Interactive Brokers"):
        _sanity_check_is_ibkr_statement("Some unrelated PDF content\nNothing to see here")


def test_accepts_gbp_and_eur_base_currency_for_ibkr_uk_and_europe_accounts():
    gbp_text = VALID_HEADER.replace("Base Currency USD", "Base Currency GBP")
    assert _parse_base_currency(gbp_text).value == "GBP"
    eur_text = VALID_HEADER.replace("Base Currency USD", "Base Currency EUR")
    assert _parse_base_currency(eur_text).value == "EUR"


def test_rejects_an_unsupported_base_currency_instead_of_silently_mislabeling():
    text = VALID_HEADER.replace("Base Currency USD", "Base Currency JPY")
    with pytest.raises(ValueError, match="JPY"):
        _parse_base_currency(text)


def test_missing_period_raises_a_clear_error():
    with pytest.raises(ValueError, match="טווח תאריכים"):
        _parse_period("Activity Statement\nInteractive Brokers LLC\nBase Currency USD")
