from datetime import date

from app.mapping.classification import classify_dividend, classify_interest
from app.mapping.nispach_d import build_nispach_d
from app.models.transactions import Currency, Dividend, InterestItem, SourceRef
from app.services.currency_service import CurrencyService

SRC = SourceRef(statement_id="stmt-1", page=7, table_name="Dividends", row_text="x")


def _dividend(symbol: str, amount: float, pay_date: date, withholding: float = 0.0) -> Dividend:
    return Dividend(
        pay_date=pay_date,
        symbol=symbol,
        isin="US0000000000",
        description="Ordinary Dividend",
        gross_amount=amount,
        withholding_tax=withholding,
        source=SRC,
    )


def test_ordinary_dividends_land_in_field_462_and_convert_to_ils():
    d1 = _dividend("MINT", 51.20, date(2025, 1, 3))
    d2 = _dividend("VCSH", 23.35, date(2025, 1, 3))
    classified = [classify_dividend(d1), classify_dividend(d2)]
    dividends_by_id = {c.source_id: d for c, d in zip(classified, [d1, d2])}

    cs = CurrencyService({(Currency.USD, date(2025, 1, 3)): 3.62})
    result = build_nispach_d(classified, dividends_by_id, cs)

    field = next(t for t in result.field_totals if t.field_income == "462")
    assert field.field_tax_paid == "431"
    assert round(field.total_income_ils, 2) == round((51.20 + 23.35) * 3.62, 2)
    assert field.item_count == 2
    assert len(result.payer_details) == 2
    assert round(result.total_foreign_income_ils, 2) == round(field.total_income_ils, 2)


def test_withholding_tax_feeds_the_paired_tax_paid_field():
    d1 = _dividend("MINT", 100.0, date(2025, 1, 3), withholding=15.0)
    classified = [classify_dividend(d1)]
    dividends_by_id = {classified[0].source_id: d1}

    cs = CurrencyService({(Currency.USD, date(2025, 1, 3)): 3.62})
    result = build_nispach_d(classified, dividends_by_id, cs)

    field = next(t for t in result.field_totals if t.field_income == "462")
    assert round(field.total_tax_paid_ils, 2) == round(15.0 * 3.62, 2)


def test_interest_does_not_auto_map_to_a_nispach_d_field():
    i = InterestItem(value_date=date(2025, 10, 3), description="USD Debit Interest", amount=-1.82, source=SRC)
    classified_interest = classify_interest(i)
    assert classified_interest.nispach_d_field is None
    assert classified_interest.needs_review is True

    # build_nispach_d should simply skip items with no target field
    cs = CurrencyService({(Currency.USD, date(2025, 10, 3)): 3.62})
    result = build_nispach_d([classified_interest], {}, cs)
    assert result.field_totals == []
    assert result.total_foreign_income_ils == 0.0


def test_fx_fallback_is_flagged_not_silent():
    d1 = _dividend("MINT", 100.0, date(2025, 6, 15))
    classified = [classify_dividend(d1)]
    dividends_by_id = {classified[0].source_id: d1}
    # only a January rate is known; June must fall back to it
    cs = CurrencyService({(Currency.USD, date(2025, 1, 1)): 3.5})
    conv = cs.convert(100.0, Currency.USD, date(2025, 6, 15))
    assert conv.is_fallback is True
    assert conv.rate_used == 3.5
