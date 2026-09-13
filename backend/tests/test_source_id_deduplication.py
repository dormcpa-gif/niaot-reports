"""Regression test for a real bug found while smoke-testing against the
real IBKR statement: two fee lines with the identical description posted
on the identical date (e.g. two quarterly "FA Fee" charges on the same
day) produced the same classify_fee() source_id. That's not just a
cosmetic duplicate-React-key issue -- source_id is the dict key for
accountant overrides and for report_service's audit-trail lookup, so two
colliding items silently shared one slot. extract_and_classify() now
disambiguates with a " #2", " #3", ... suffix, and report_service()
matches classified items back to their raw source records by list
position instead of recomputing/string-matching that id."""

from __future__ import annotations

from datetime import date

from app.mapping.classification import ClassifiedItem
from app.models.transactions import Currency, FeeItem, InterestItem, NormalizedStatement, SourceRef
from app.services.currency_service import CurrencyService
from app.services.extraction_service import _dedupe_source_id
from app.services.report_service import build_appendix_report


def test_dedupe_source_id_leaves_the_first_occurrence_untouched():
    seen: dict[str, int] = {}
    assert _dedupe_source_id(seen, "Fee X 2025-04-01") == "Fee X 2025-04-01"


def test_dedupe_source_id_suffixes_subsequent_collisions():
    seen: dict[str, int] = {}
    first = _dedupe_source_id(seen, "Fee X 2025-04-01")
    second = _dedupe_source_id(seen, "Fee X 2025-04-01")
    third = _dedupe_source_id(seen, "Fee X 2025-04-01")
    assert (first, second, third) == ("Fee X 2025-04-01", "Fee X 2025-04-01 #2", "Fee X 2025-04-01 #3")


def test_dedupe_source_id_does_not_touch_genuinely_distinct_ids():
    seen: dict[str, int] = {}
    a = _dedupe_source_id(seen, "Fee X 2025-04-01")
    b = _dedupe_source_id(seen, "Fee Y 2025-04-01")
    assert (a, b) == ("Fee X 2025-04-01", "Fee Y 2025-04-01")


def _fee(description: str, value_date: date, amount: float, row_text: str) -> FeeItem:
    return FeeItem(
        description=description,
        value_date=value_date,
        amount=amount,
        source=SourceRef(statement_id="stmt-1", page=1, table_name="Advisor Fees", row_text=row_text),
    )


def test_report_service_cites_the_correct_row_for_each_deduplicated_fee():
    """End-to-end: two colliding fee source_ids must still each resolve
    to their OWN row_text in the explanation report, not silently lose
    the second one's citation (which is what recompute-and-string-match
    used to do once the id was disambiguated)."""
    fee1 = _fee("FA Fee: Percent of Equity, Posted Quarterly", date(2025, 4, 1), -100.0, "row A -100.00")
    fee2 = _fee("FA Fee: Percent of Equity, Posted Quarterly", date(2025, 4, 1), -50.0, "row B -50.00")

    statement = NormalizedStatement(
        statement_id="stmt-1",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 12, 31),
        fees=[fee1, fee2],
    )

    classified = [
        ClassifiedItem(
            source_kind="fee",
            source_id="FA Fee: Percent of Equity, Posted Quarterly 2025-04-01",
            nispach_d_field=None,
            amount_source_ccy=-100.0,
            currency=Currency.USD,
            value_date=date(2025, 4, 1),
        ),
        ClassifiedItem(
            source_kind="fee",
            source_id="FA Fee: Percent of Equity, Posted Quarterly 2025-04-01 #2",
            nispach_d_field=None,
            amount_source_ccy=-50.0,
            currency=Currency.USD,
            value_date=date(2025, 4, 1),
        ),
    ]

    cs = CurrencyService({(Currency.USD, date(2025, 4, 1)): 3.6})
    report = build_appendix_report(statement, classified, {}, cs)

    assert len(report.explanation_rows) == 2
    assert report.explanation_rows[0].source_row_text == "row A -100.00"
    assert report.explanation_rows[1].source_row_text == "row B -50.00"


def test_report_service_still_matches_a_single_interest_record_by_position():
    item_source = SourceRef(statement_id="stmt-1", page=1, table_name="Interest", row_text="the only interest row")
    interest = InterestItem(value_date=date(2025, 10, 3), description="USD Debit Interest", amount=-1.82, source=item_source)
    statement = NormalizedStatement(
        statement_id="stmt-1", period_start=date(2025, 1, 1), period_end=date(2025, 12, 31), interest=[interest]
    )
    classified = [
        ClassifiedItem(
            source_kind="interest",
            source_id="USD Debit Interest 2025-10-03",
            nispach_d_field=None,
            amount_source_ccy=-1.82,
            currency=Currency.USD,
            value_date=date(2025, 10, 3),
        )
    ]
    cs = CurrencyService({(Currency.USD, date(2025, 10, 3)): 3.62})
    report = build_appendix_report(statement, classified, {}, cs)
    assert report.explanation_rows[0].source_row_text == "the only interest row"
