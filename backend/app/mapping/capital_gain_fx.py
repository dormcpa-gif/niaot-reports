"""ILS value of one capital-gain trade.

Israeli rule for a foreign security held by an individual: the exchange
rate is the "index", so the gain is computed in shekels from each leg's
own date, and the inflationary (FX) part is exempt:

    nominal   = sale_cash x rate(sale date) - purchase_cost x rate(purchase date)
    real      = clamp(usd_gain x rate(closing date), between 0 and nominal)
    inflation = nominal - real            (exempt)

The clamp keeps "real" from exceeding the nominal gain in magnitude or
flipping its sign when the two dates' rates diverge sharply -- it mirrors
the accountant's own workpaper formula (see tax_analysis_system_prompt.md
section 4.1). The closing date is the date the position was closed: the
sale for a normal trade, the buy-back for a short sale.

When a lot's open date is unknown (or its rate is missing) the nominal
gain cannot be computed; the result falls back to usd_gain x closing-rate
with no clamp and says so in `note`, because that can overstate the gain.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from app.mapping.classification import ClassifiedItem
from app.services.currency_service import CurrencyService


class TradeIls(BaseModel):
    real_ils: float
    nominal_ils: float
    inflationary_ils: float
    close_rate: float
    buy_rate: float | None = None
    sell_rate: float | None = None
    note: str | None = None


def clamp_real(raw_real: float, nominal: float) -> float:
    if nominal > 0:
        return max(0.0, min(raw_real, nominal))
    if nominal < 0:
        return min(0.0, max(raw_real, nominal))
    return 0.0


def convert_trade_item(
    item: ClassifiedItem, currency_service: CurrencyService, acquisition_dates: dict[str, date] | None = None
) -> TradeIls:
    close = currency_service.convert(item.amount_source_ccy, item.currency, item.value_date)
    raw_real = round(item.amount_source_ccy * close.rate_used, 2)

    def fallback(reason: str | None) -> TradeIls:
        return TradeIls(real_ils=raw_real, nominal_ils=raw_real, inflationary_ils=0.0, close_rate=close.rate_used, note=reason)

    if not item.lot_level or item.proceeds_source_ccy is None or item.cost_source_ccy is None:
        return fallback(None)

    open_date = item.open_date or (acquisition_dates or {}).get(item.symbol or "")
    if open_date is None:
        return fallback("תאריך רכישה לא ידוע - הרווח חושב בשער יום הסגירה בלבד, ללא הגבלת הרווח הריאלי (עלול להיות מוגזם).")

    sell_date, buy_date = (open_date, item.value_date) if item.is_short else (item.value_date, open_date)
    try:
        sell = currency_service.convert(item.proceeds_source_ccy, item.currency, sell_date)
        buy = currency_service.convert(item.cost_source_ccy, item.currency, buy_date)
    except ValueError:
        return fallback(f"חסר שער המרה לתאריך {open_date.isoformat()} - הרווח חושב בשער יום הסגירה בלבד, ללא הגבלה.")

    nominal = round(item.proceeds_source_ccy * sell.rate_used - item.cost_source_ccy * buy.rate_used, 2)
    real = round(clamp_real(raw_real, nominal), 2)
    return TradeIls(
        real_ils=real,
        nominal_ils=nominal,
        inflationary_ils=round(nominal - real, 2),
        close_rate=close.rate_used,
        buy_rate=buy.rate_used,
        sell_rate=sell.rate_used,
    )
