"""Classification rules for turning normalized IBKR transactions into
appendix line items.

Guardrail (see plan): nothing that requires a professional/legal judgment
call is decided silently. Every classification below carries a
`needs_review` flag; the review UI must let the accountant confirm or
override it before a report is finalized. Defaults are the *most common*
case, not a guaranteed-correct one.
"""

from __future__ import annotations

from datetime import date as date_type
from enum import Enum

from pydantic import BaseModel

from app.models.transactions import Currency, Dividend, FeeItem, InterestItem, Trade


class NispachDBracket(str, Enum):
    """Nispach D field-pair codes, named after the 'total income' field
    number (the right-hand field in the form; each has a matching
    'tax paid abroad' field on the left, see NISPACH_D_FIELD_PAIRS)."""

    DIVIDEND_25 = "462"  # דיבידנד והכנסות אחרות - מס בשיעור 25%
    DIVIDEND_CONTROLLING_30 = "455"  # דיבידנד לבעל מניות מהותי - מס בשיעור 30%
    INTEREST_SECURITIES_15 = "460"  # ריבית, הפרשי הצמדה, דמי ניכיון - 15%
    INTEREST_DEPOSIT_20 = "451"  # ריבית מני"ע/פיקדונות/תוכניות חיסכון - 20%
    INTEREST_DEPOSIT_25 = "457"  # ריבית מני"ע/פיקדונות/תוכניות חיסכון - 25%
    INTEREST_35 = "453"  # ריבית - מס בשיעור 35%


# maps a "total income" field -> its paired "tax paid abroad" field, per
# the official Nispach D layout we reviewed.
NISPACH_D_FIELD_PAIRS: dict[str, str] = {
    "462": "431",
    "455": "413",
    "460": "412",
    "451": "428",
    "457": "417",
    "453": "415",
}

NISPACH_D_FIELD_LABELS: dict[str, str] = {
    "462": 'מדיבידנד והכנסות אחרות - מס בשיעור 25%',
    "455": 'דיבידנד לבעל מניות מהותי - מס בשיעור 30%',
    "460": 'ריבית, הפרשי הצמדה, דמי ניכיון - מס בשיעור 15%',
    "451": 'ריבית ני"ע/פיקדונות/תוכניות חיסכון - מס בשיעור 20%',
    "457": 'ריבית ני"ע/פיקדונות/תוכניות חיסכון - מס בשיעור 25%',
    "453": "ריבית - מס בשיעור 35%",
}


class ClassifiedItem(BaseModel):
    source_kind: str  # "dividend" | "interest" | "trade" | "fee"
    source_id: str  # symbol/description, for traceability
    nispach_d_field: str | None  # e.g. "462"; None if it doesn't map to Nispach D
    amount_source_ccy: float  # native statement currency
    currency: Currency = Currency.USD  # which currency amount_source_ccy/withholding_source_ccy are in
    value_date: date_type  # used to look up the FX rate for ILS conversion
    withholding_source_ccy: float = 0.0
    needs_review: bool = False
    review_reason: str | None = None


def classify_dividend(d: Dividend) -> ClassifiedItem:
    """Ordinary cash dividends default to the 25% 'dividend and other
    income' bracket (field 462). A dividend from a company where the
    client is a 'controlling shareholder' (בעל מניות מהותי) belongs in
    field 455 (30%) instead -- that determination needs the accountant,
    since it depends on the client's overall shareholding, not anything
    visible in a brokerage statement."""
    return ClassifiedItem(
        source_kind="dividend",
        source_id=f"{d.symbol} {d.pay_date.isoformat()}",
        nispach_d_field=NispachDBracket.DIVIDEND_25.value,
        amount_source_ccy=d.gross_amount,
        currency=d.currency,
        value_date=d.pay_date,
        withholding_source_ccy=d.withholding_tax,
        needs_review=True,
        review_reason='ברירת מחדל: דיבידנד רגיל (25%, שדה 462). יש לאמת שאין "בעל מניות מהותי" (שדה 455/30%).',
    )


def classify_interest(i: InterestItem) -> ClassifiedItem:
    """Interest cannot be auto-classified into a tax-rate bracket:
    IBKR's own 'Interest' line (credit/debit interest on cash balances)
    doesn't say whether Israeli law treats it as securities interest
    (15%/25%) or deposit interest (20%/25%/35%) -- that depends on the
    instrument, which the accountant must pick from the review screen."""
    return ClassifiedItem(
        source_kind="interest",
        source_id=f"{i.description} {i.value_date.isoformat()}",
        nispach_d_field=None,
        amount_source_ccy=i.amount,
        currency=i.currency,
        value_date=i.value_date,
        needs_review=True,
        review_reason="ריבית: יש לבחור ידנית את מדרגת המס הנכונה (412/428/417/415) בהתאם לסוג המכשיר.",
    )


def classify_trade(t: Trade) -> ClassifiedItem:
    """Realized capital gains go to Nispach C, not directly to a
    Nispach D dividend/interest field. The IBKR Short/Long-Term split is
    kept as informational context only -- Israeli securities
    capital-gains brackets are not determined by US holding-period
    rules, so the accountant still picks/confirms the Nispach C
    tax-rate column (see mapping/nispach_c.py)."""
    return ClassifiedItem(
        source_kind="trade",
        source_id=f"{t.symbol} ({t.holding_term.value}-term, {t.close_date.isoformat()})",
        nispach_d_field=None,
        amount_source_ccy=t.realized_pnl,
        currency=t.currency,
        value_date=t.close_date,
        needs_review=True,
        review_reason='רווח/הפסד הון ממכירת ני"ע: מועבר לנספח ג\'. יש לאמת את מדרגת המס (35/30/25/20/15%).',
    )


def classify_fee(f: FeeItem) -> ClassifiedItem:
    """Advisor fees / commissions are shown for context only in the
    explanation report. Whether (and how) they're deductible is a
    professional judgment call this MVP does not attempt to automate."""
    return ClassifiedItem(
        source_kind="fee",
        source_id=f"{f.description} {f.value_date.isoformat()}",
        nispach_d_field=None,
        amount_source_ccy=f.amount,
        currency=f.currency,
        value_date=f.value_date,
        needs_review=True,
        review_reason="עמלה/דמי ניהול: אינפורמטיבי בלבד, לא ממופה אוטומטית לשדה בטופס.",
    )
