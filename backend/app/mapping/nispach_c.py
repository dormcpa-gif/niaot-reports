"""Builds the Nispach C (רווח הון מניירות ערך סחירים) appendix output.

Scope note (see plan): the official Nispach C table also has rows for
offsetting current/carried-forward securities losses against the gain,
and losses against interest/dividend income -- those depend on the
client's loss-carryforward history from prior years, which isn't
available from a single broker statement. This module only produces the
"gross realized gain, before loss offsets" figure per tax-rate bracket
plus the best-effort total sale proceeds; the accountant still has to
apply any loss offsets in the official system.

Tax-rate bracket: Nispach C's columns (35% / 30% / 25% / 20% / 15%) are
not the US short/long holding-period distinction. We default every
realized gain into the 25% column (the common case for an individual's
foreign securities) and mark it as needing the accountant's
confirmation -- see app/mapping/classification.py.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.mapping.classification import ClassifiedItem
from app.models.transactions import Currency
from app.services.currency_service import CurrencyService

DEFAULT_BRACKET = "25"
BRACKETS = ("35", "30", "25", "20", "15")


class NispachCBracketTotal(BaseModel):
    tax_rate_percent: str  # "35" | "30" | "25" | "20" | "15"
    gross_gain_ils: float
    item_count: int


class NispachCResult(BaseModel):
    bracket_totals: list[NispachCBracketTotal]
    total_sale_proceeds_ils: float  # "סכום המכירות" -- best-effort, see module docstring
    total_gain_ils: float  # goes to Form 1301 fields 137/138/139 via Nispach D 420/422
    needs_review: bool = True


def build_nispach_c(
    classified_trades: list[ClassifiedItem],
    sale_proceeds_by_symbol_native: dict[str, float],
    currency_service: CurrencyService,
    bracket_overrides: dict[str, str] | None = None,
    base_currency: Currency = Currency.USD,
) -> NispachCResult:
    """bracket_overrides: {source_id: "30"} to move a specific trade out
    of the 25% default bracket, as confirmed by the accountant.

    sale_proceeds_by_symbol_native / base_currency: the per-symbol totals
    come from the statement's own base currency (USD for a US IBKR
    account, GBP/EUR for an IBKR UK/Europe account) -- pass the
    statement's base_currency so the FX conversion below uses the right
    rate table lookup instead of assuming USD."""
    overrides = bracket_overrides or {}
    totals: dict[str, NispachCBracketTotal] = {
        b: NispachCBracketTotal(tax_rate_percent=b, gross_gain_ils=0.0, item_count=0) for b in BRACKETS
    }

    for item in classified_trades:
        bracket = overrides.get(item.source_id, DEFAULT_BRACKET)
        conv = currency_service.convert(item.amount_source_ccy, item.currency, item.value_date)
        totals[bracket].gross_gain_ils = round(totals[bracket].gross_gain_ils + conv.ils_amount, 2)
        totals[bracket].item_count += 1

    proceeds_total_ils = 0.0
    for symbol, proceeds_native in sale_proceeds_by_symbol_native.items():
        if proceeds_native <= 0:
            continue  # net buyer for the year; not a sale
        # Symbol-level proceeds don't carry a single date (multiple lots);
        # use the latest trade date we have for that symbol as a
        # reasonable FX-rate anchor, falling back to no conversion info.
        matching_dates = [i.value_date for i in classified_trades if i.source_id.startswith(f"{symbol} (")]
        on_date = max(matching_dates) if matching_dates else None
        if on_date is None:
            continue
        conv = currency_service.convert(proceeds_native, base_currency, on_date)
        proceeds_total_ils += conv.ils_amount

    return NispachCResult(
        bracket_totals=[t for t in totals.values() if t.item_count > 0],
        total_sale_proceeds_ils=round(proceeds_total_ils, 2),
        total_gain_ils=round(sum(t.gross_gain_ils for t in totals.values()), 2),
    )
