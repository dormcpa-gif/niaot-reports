"""Official Bank of Israel representative exchange rates.

The per-lot capital-gain conversion needs a rate for every purchase and
sale date (including prior years), which is impractical to type in by
hand. The Bank of Israel publishes the representative rate for each
business day through its public SDMX API; this module fetches exactly
the range a report needs.

Nothing here invents a rate: a failed request, an unknown currency or an
empty answer raises BoiRatesUnavailable with a message for the user, so
the report is never produced from silently missing data. Weekends and
holidays have no published rate -- CurrencyService already falls back to
the nearest earlier date and flags it.
"""

from __future__ import annotations

import csv
import io
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import date, timedelta

from app.models.transactions import Currency

_BASE_URL = "https://edge.boi.org.il/FusionEdgeServer/sdmx/v2/data/dataflow/BOI.STATISTICS/EXR/1.0"
_SERIES = {Currency.USD: "RER_USD_ILS", Currency.EUR: "RER_EUR_ILS", Currency.GBP: "RER_GBP_ILS"}
_TIMEOUT_SECONDS = 30
LOOKBACK_DAYS = 10  # covers a long weekend / holiday run before the earliest date

Fetcher = Callable[[str], str]


class BoiRatesUnavailable(ValueError):
    """The official rates could not be obtained; the message is user-facing."""


def _http_get(url: str) -> str:
    try:
        with urllib.request.urlopen(url, timeout=_TIMEOUT_SECONDS) as resp:  # noqa: S310 - fixed https host
            return resp.read().decode("utf-8-sig")
    except urllib.error.HTTPError as e:
        raise BoiRatesUnavailable(f"בנק ישראל החזיר שגיאה {e.code} בשליפת שערי המרה.") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise BoiRatesUnavailable(
            "לא ניתן להתחבר לבנק ישראל לשליפת שערי המרה. אפשר להזין שערים ידנית או לנסות שוב."
        ) from e


def parse_boi_csv(body: str, currency: Currency) -> dict[tuple[Currency, date], float]:
    rows = csv.DictReader(io.StringIO(body))
    if not rows.fieldnames or not {"TIME_PERIOD", "OBS_VALUE"} <= set(rows.fieldnames):
        raise BoiRatesUnavailable("תשובת בנק ישראל אינה בפורמט הצפוי - לא נעשה שימוש בשערים.")
    out: dict[tuple[Currency, date], float] = {}
    for row in rows:
        try:
            day = date.fromisoformat(row["TIME_PERIOD"])
            rate = float(row["OBS_VALUE"])
        except (KeyError, ValueError, TypeError) as e:
            raise BoiRatesUnavailable("תשובת בנק ישראל אינה בפורמט הצפוי - לא נעשה שימוש בשערים.") from e
        if rate <= 0:
            raise BoiRatesUnavailable(f"בנק ישראל החזיר שער לא תקין ({rate}) לתאריך {day.isoformat()}.")
        out[(currency, day)] = rate
    return out


def fetch_boi_rates(
    currency: Currency, start: date, end: date, fetch: Fetcher | None = None
) -> dict[tuple[Currency, date], float]:
    """Published rates for `currency` on every business day in [start, end]."""
    series = _SERIES.get(currency)
    if series is None:
        raise BoiRatesUnavailable(f"אין שער יציג של בנק ישראל למטבע {currency.value}.")
    url = f"{_BASE_URL}/{series}?startperiod={start.isoformat()}&endperiod={end.isoformat()}&format=csv"
    rates = parse_boi_csv((fetch or _http_get)(url), currency)
    if not rates:
        raise BoiRatesUnavailable(
            f"בנק ישראל לא החזיר שערי {currency.value} לטווח {start.isoformat()} עד {end.isoformat()}."
        )
    return rates


def fetch_rates_covering(
    currencies: set[Currency], dates: list[date], fetch: Fetcher | None = None
) -> dict[tuple[Currency, date], float]:
    """Rates for every currency over the span of `dates`, starting
    LOOKBACK_DAYS earlier so the earliest date can fall back."""
    if not dates:
        return {}
    start = min(dates) - timedelta(days=LOOKBACK_DAYS)
    end = min(max(dates), date.today())
    out: dict[tuple[Currency, date], float] = {}
    for currency in sorted(currencies - {Currency.ILS}, key=lambda c: c.value):
        out.update(fetch_boi_rates(currency, start, end, fetch))
    return out
