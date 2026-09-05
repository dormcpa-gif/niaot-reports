"""USD -> ILS conversion for appendix amounts.

Nispach C / Nispach D are denominated in shekels, so every USD figure
extracted from a broker statement needs a Bank of Israel representative
exchange rate applied before it can go into the appendix.

Design: this is intentionally a thin, overridable lookup, not a silent
"correct" computation --
- Default behavior: one rate per (currency, date), looked up from a rate
  table the caller supplies (loaded from a CSV of Bank of Israel
  representative rates, or entered manually for a quick run).
- If no exact-date rate is available, falls back to the nearest earlier
  date in the table and flags the result so the accountant can see a
  fallback was used -- it never silently invents a rate.
- The accountant can always override the *methodology* (transaction-date
  rate vs. a single annual average, as some Tax Authority guidance
  permits) by supplying a different rate table; this module doesn't
  hard-code which method is "correct".
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from app.models.transactions import Currency


class ConversionResult(BaseModel):
    ils_amount: float
    rate_used: float
    rate_date: date
    is_fallback: bool  # True if the exact transaction date had no rate and we used the nearest earlier one


class CurrencyService:
    def __init__(self, rates: dict[tuple[Currency, date], float]):
        # rates: {(USD, 2025-01-03): 3.62, ...}
        self._rates = dict(rates)

    def convert(self, amount: float, currency: Currency, on_date: date) -> ConversionResult:
        if currency == Currency.ILS:
            return ConversionResult(ils_amount=round(amount, 2), rate_used=1.0, rate_date=on_date, is_fallback=False)

        exact = self._rates.get((currency, on_date))
        if exact is not None:
            return ConversionResult(
                ils_amount=round(amount * exact, 2), rate_used=exact, rate_date=on_date, is_fallback=False
            )

        candidates = [d for (ccy, d) in self._rates if ccy == currency and d <= on_date]
        if not candidates:
            raise ValueError(
                f"No exchange rate available for {currency.value} on or before {on_date.isoformat()}. "
                "Supply a rate table covering the statement period."
            )
        nearest = max(candidates)
        rate = self._rates[(currency, nearest)]
        return ConversionResult(ils_amount=round(amount * rate, 2), rate_used=rate, rate_date=nearest, is_fallback=True)


def load_rates_from_csv_rows(rows: list[tuple[str, str, float]]) -> dict[tuple[Currency, date], float]:
    """rows: (currency_code, iso_date, rate) tuples, e.g. from a CSV of
    Bank of Israel representative rates the accountant maintains."""
    out: dict[tuple[Currency, date], float] = {}
    for ccy_code, iso_date, rate in rows:
        out[(Currency(ccy_code), date.fromisoformat(iso_date))] = float(rate)
    return out
