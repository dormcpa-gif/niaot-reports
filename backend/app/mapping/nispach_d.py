"""Builds the Nispach D (הכנסות חו"ל) appendix output from classified items.

Field numbers here are taken directly from the official Nispach D form
(ניספח ד לטופס 1301) we reviewed with the accountant -- see
app/mapping/classification.py for the field-pair table and labels.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.mapping.classification import (
    NISPACH_D_FIELD_LABELS,
    NISPACH_D_FIELD_PAIRS,
    ClassifiedItem,
)
from app.models.transactions import Currency, Dividend
from app.services.currency_service import CurrencyService


class NispachDFieldTotal(BaseModel):
    field_income: str  # e.g. "462"
    field_tax_paid: str  # e.g. "431"
    label: str
    total_income_ils: float
    total_tax_paid_ils: float
    item_count: int
    needs_review: bool


class PayerDetailRow(BaseModel):
    """One row of the 'פרוטים לנספח ד' payer-detail page (page 3 of the
    real form): payer, country, amount -- for a given Nispach D field."""

    field_income: str
    payer: str
    country: str
    amount_ils: float


class NispachDResult(BaseModel):
    field_totals: list[NispachDFieldTotal]
    payer_details: list[PayerDetailRow]
    total_foreign_income_ils: float  # summed box carried to Form 1301 field 130/159


def build_nispach_d(
    classified: list[ClassifiedItem],
    dividends_by_id: dict[str, Dividend],
    currency_service: CurrencyService,
    default_country: str = 'ארה"ב',
) -> NispachDResult:
    field_totals: dict[str, NispachDFieldTotal] = {}
    payer_details: list[PayerDetailRow] = []

    for item in classified:
        if item.nispach_d_field is None:
            continue
        field = item.nispach_d_field
        tax_paid_field = NISPACH_D_FIELD_PAIRS[field]

        income_conv = currency_service.convert(item.amount_source_ccy, Currency.USD, item.value_date)
        tax_conv = currency_service.convert(item.withholding_source_ccy, Currency.USD, item.value_date)

        if item.source_kind == "dividend":
            div = dividends_by_id.get(item.source_id)
            payer_details.append(
                PayerDetailRow(
                    field_income=field,
                    payer=div.symbol if div is not None else item.source_id,
                    country=default_country,
                    amount_ils=income_conv.ils_amount,
                )
            )

        if field not in field_totals:
            field_totals[field] = NispachDFieldTotal(
                field_income=field,
                field_tax_paid=tax_paid_field,
                label=NISPACH_D_FIELD_LABELS.get(field, field),
                total_income_ils=0.0,
                total_tax_paid_ils=0.0,
                item_count=0,
                needs_review=False,
            )
        totals = field_totals[field]
        totals.total_income_ils = round(totals.total_income_ils + income_conv.ils_amount, 2)
        totals.total_tax_paid_ils = round(totals.total_tax_paid_ils + tax_conv.ils_amount, 2)
        totals.item_count += 1
        totals.needs_review = totals.needs_review or item.needs_review

    total_foreign_income = sum(t.total_income_ils for t in field_totals.values())

    return NispachDResult(
        field_totals=sorted(field_totals.values(), key=lambda t: t.field_income),
        payer_details=payer_details,
        total_foreign_income_ils=round(total_foreign_income, 2),
    )
