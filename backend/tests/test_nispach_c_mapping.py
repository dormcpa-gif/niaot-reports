from datetime import date

from app.mapping.classification import classify_trade
from app.mapping.nispach_c import build_nispach_c
from app.models.transactions import Currency, HoldingTerm, SourceRef, Trade
from app.services.currency_service import CurrencyService

SRC = SourceRef(statement_id="stmt-1", page=2, table_name="Realized & Unrealized Performance Summary", row_text="x")


def _trade(symbol: str, pnl: float, term: HoldingTerm, close_date: date) -> Trade:
    return Trade(
        symbol=symbol,
        close_date=close_date,
        proceeds=0.0,
        cost_basis=0.0,
        realized_pnl=pnl,
        holding_term=term,
        source=SRC,
    )


def test_gains_default_to_25_percent_bracket():
    t1 = _trade("QQQ", 6424.46, HoldingTerm.LONG, date(2025, 9, 11))
    t2 = _trade("FDN", 2318.28, HoldingTerm.SHORT, date(2025, 8, 12))
    classified = [classify_trade(t1), classify_trade(t2)]

    cs = CurrencyService({(Currency.USD, date(2025, 9, 11)): 3.6, (Currency.USD, date(2025, 8, 12)): 3.6})
    result = build_nispach_c(classified, {}, cs)

    assert len(result.bracket_totals) == 1
    bracket = result.bracket_totals[0]
    assert bracket.tax_rate_percent == "25"
    assert bracket.item_count == 2
    # each item is converted to ILS and rounded individually before summing
    # (matches how the mapping code accumulates), not rounded once at the end
    expected = round(round(6424.46 * 3.6, 2) + round(2318.28 * 3.6, 2), 2)
    assert round(bracket.gross_gain_ils, 2) == expected


def test_bracket_override_moves_a_trade_to_a_different_column():
    t1 = _trade("QQQ", 1000.0, HoldingTerm.LONG, date(2025, 9, 11))
    classified = [classify_trade(t1)]
    cs = CurrencyService({(Currency.USD, date(2025, 9, 11)): 3.6})

    result = build_nispach_c(classified, {}, cs, bracket_overrides={classified[0].source_id: "30"})

    assert len(result.bracket_totals) == 1
    assert result.bracket_totals[0].tax_rate_percent == "30"


def test_sale_proceeds_only_counts_net_sellers():
    t1 = _trade("QQQ", 1000.0, HoldingTerm.LONG, date(2025, 9, 11))
    classified = [classify_trade(t1)]
    cs = CurrencyService({(Currency.USD, date(2025, 9, 11)): 3.6})

    # BSJQ was a net buyer (negative proceeds) and must be excluded from "total sales"
    proceeds = {"QQQ": 5000.0, "BSJQ": -10112.72}
    result = build_nispach_c(classified, proceeds, cs)

    assert round(result.total_sale_proceeds_ils, 2) == round(5000.0 * 3.6, 2)
