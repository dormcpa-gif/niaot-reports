"""Per-lot capital gains: execution parsing, FIFO lot matching, and the
Israeli shekel conversion (each leg at its own date, real gain clamped
to the nominal gain). All numbers are synthetic."""

from datetime import date

from app.mapping.capital_gain_fx import clamp_real, convert_trade_item
from app.mapping.classification import classify_trade
from app.mapping.nispach_c import build_nispach_c
from app.models.transactions import Currency, HoldingTerm, NormalizedStatement, SourceRef, Trade, TradeExecution
from app.parsers.ibkr_activity import parse_trade_executions_text
from app.services.currency_service import CurrencyService
from app.services.lot_matching import apply_lot_matching, match_lots

SRC = SourceRef(statement_id="s", page=5, table_name="Trades", row_text="x")

TRADES_TEXT = """
Trades
Account Symbol Date/Time Quantity T. Price C. Price Proceeds Comm/Fee Basis Realized P/L MTM P/L Code
Stocks
USD
2025-03-10,
U1234567 ABC -100 12.0000 11.5000 1,200.00 -1.00 -1,001.00 198.00 50.00 C;P
10:15:00
2025-06-17, 698.78093333
U1234567 XYZ -300 697.2300 209,634.28 -2.07 -198,540.73 11,091.48 465.28 C;P
09:30:00
Total ABC 0 1,200.00 -1.00 0.00 198.00 50.00
"""


def _ex(day: date, qty: float, proceeds: float, comm: float = -1.0, basis: float = 0.0, code: str = "O;P", symbol: str = "ABC") -> TradeExecution:
    return TradeExecution(
        account="U1234567", symbol=symbol, executed_on=day, quantity=qty, price=0.0,
        proceeds=proceeds, commission=comm, basis=basis, realized_pnl=0.0, code=code, source=SRC,
    )


def _cs(rates: dict[date, float]) -> CurrencyService:
    return CurrencyService({(Currency.USD, d): r for d, r in rates.items()})


def _item(trade: Trade):
    return classify_trade(trade)


# ---- parsing ----


def test_parse_execution_row_with_date_on_previous_line():
    rows = parse_trade_executions_text(TRADES_TEXT, "s", 5)
    abc = next(r for r in rows if r.symbol == "ABC")
    assert abc.executed_on == date(2025, 3, 10)
    assert abc.quantity == -100
    assert abc.price == 12.0
    assert abc.proceeds == 1200.00
    assert abc.commission == -1.00
    assert abc.basis == -1001.00
    assert abc.realized_pnl == 198.00
    assert abc.code == "C;P"
    assert abc.account == "U1234567"


def test_parse_execution_row_whose_price_wrapped_onto_the_date_line():
    rows = parse_trade_executions_text(TRADES_TEXT, "s", 5)
    xyz = next(r for r in rows if r.symbol == "XYZ")
    assert xyz.executed_on == date(2025, 6, 17)
    assert xyz.price == 698.78093333
    assert xyz.quantity == -300
    assert xyz.realized_pnl == 11091.48


def test_total_rows_are_not_executions():
    rows = parse_trade_executions_text(TRADES_TEXT, "s", 5)
    assert len(rows) == 2


# ---- lot matching ----


def test_long_round_trip_becomes_one_lot_with_both_dates():
    lots = match_lots([_ex(date(2025, 1, 10), 100, -1000), _ex(date(2025, 3, 10), -100, 1200, code="C;P")], "s")
    assert len(lots) == 1
    lot = lots[0]
    assert (lot.open_date, lot.close_date, lot.is_short) == (date(2025, 1, 10), date(2025, 3, 10), False)
    assert lot.proceeds == 1199.0 and lot.cost_basis == 1001.0 and lot.realized_pnl == 198.0


def test_short_sale_round_trip_marks_the_lot_short():
    lots = match_lots([_ex(date(2025, 1, 10), -100, 1200), _ex(date(2025, 3, 10), 100, -1000, code="C;P")], "s")
    assert len(lots) == 1
    lot = lots[0]
    assert lot.is_short is True
    assert (lot.open_date, lot.close_date) == (date(2025, 1, 10), date(2025, 3, 10))
    assert lot.realized_pnl == 198.0


def test_fifo_splits_one_sale_across_two_purchases():
    lots = match_lots(
        [
            _ex(date(2025, 1, 10), 100, -1000),
            _ex(date(2025, 2, 10), 50, -550),
            _ex(date(2025, 3, 10), -120, 1440, code="C;P"),
        ],
        "s",
    )
    assert [(l.open_date, round(l.cost_basis, 2)) for l in lots] == [(date(2025, 1, 10), 1001.0), (date(2025, 2, 10), 220.4)]
    assert round(sum(l.realized_pnl for l in lots), 2) == round(1440 - 1 - (1000 + 1) - 550 * 20 / 50 - 20 / 50, 2)


def test_closing_a_position_not_in_the_statement_uses_ibkr_basis_and_is_flagged():
    lots = match_lots([_ex(date(2025, 3, 10), -100, 1200, basis=-1001.0, code="C;P")], "s")
    assert len(lots) == 1
    assert lots[0].open_date is None
    assert lots[0].realized_pnl == 198.0
    assert lots[0].note and "תאריך הרכישה" in lots[0].note


def test_lots_replace_summary_trade_only_when_they_reconcile():
    summary = Trade(
        symbol="ABC", close_date=date(2025, 12, 31), proceeds=0, cost_basis=0, realized_pnl=198.0,
        holding_term=HoldingTerm.SHORT, source=SRC,
    )
    execs = [_ex(date(2025, 1, 10), 100, -1000), _ex(date(2025, 3, 10), -100, 1200, code="C;P")]

    def stmt(summary_pnl: float) -> NormalizedStatement:
        t = summary.model_copy(update={"realized_pnl": summary_pnl})
        return NormalizedStatement(
            statement_id="s", period_start=date(2025, 1, 1), period_end=date(2025, 12, 31), trades=[t], executions=execs
        )

    ok = apply_lot_matching(stmt(198.0))
    assert [t.lot_level for t in ok.trades] == [True] and ok.warnings == []

    bad = apply_lot_matching(stmt(500.0))
    assert [t.lot_level for t in bad.trades] == [False]
    assert len(bad.warnings) == 1 and "ABC" in bad.warnings[0]


# ---- shekel conversion ----


def test_clamp_real_never_exceeds_nominal_or_flips_its_sign():
    assert clamp_real(732.6, 832.7) == 732.6
    assert clamp_real(932.6, 832.7) == 832.7
    assert clamp_real(594.0, -407.0) == 0.0
    assert clamp_real(-933.7, -743.4) == -743.4
    assert clamp_real(-100.0, -743.4) == -100.0
    assert clamp_real(50.0, 0.0) == 0.0


def test_long_lot_real_gain_is_usd_gain_at_the_closing_rate():
    lot = match_lots([_ex(date(2025, 1, 10), 100, -1000), _ex(date(2025, 3, 10), -100, 1200, code="C;P")], "s")[0]
    cs = _cs({date(2025, 1, 10): 3.6, date(2025, 3, 10): 3.7})
    ils = convert_trade_item(_item(lot), cs)
    assert ils.nominal_ils == round(1199 * 3.7 - 1001 * 3.6, 2) == 832.7
    assert ils.real_ils == round(198 * 3.7, 2) == 732.6
    assert ils.inflationary_ils == 100.1
    assert (ils.buy_rate, ils.sell_rate, ils.close_rate) == (3.6, 3.7, 3.7)


def test_shekel_strengthening_can_turn_a_dollar_gain_into_zero_real_gain():
    lot = match_lots([_ex(date(2025, 1, 10), 100, -1000), _ex(date(2025, 3, 10), -100, 1200, code="C;P")], "s")[0]
    cs = _cs({date(2025, 1, 10): 4.0, date(2025, 3, 10): 3.0})
    ils = convert_trade_item(_item(lot), cs)
    assert ils.nominal_ils == round(1199 * 3.0 - 1001 * 4.0, 2) == -407.0
    assert ils.real_ils == 0.0
    assert ils.inflationary_ils == -407.0


def test_short_sale_uses_the_buy_back_date_as_the_closing_rate():
    lot = match_lots([_ex(date(2025, 1, 10), -100, 1200), _ex(date(2025, 3, 10), 100, -1000, code="C;P")], "s")[0]
    cs = _cs({date(2025, 1, 10): 3.6, date(2025, 3, 10): 3.7})
    ils = convert_trade_item(_item(lot), cs)
    assert ils.sell_rate == 3.6 and ils.buy_rate == 3.7 and ils.close_rate == 3.7
    assert ils.nominal_ils == round(1199 * 3.6 - 1001 * 3.7, 2) == 612.7
    assert ils.real_ils == 612.7  # 198 x 3.7 = 732.6 exceeds nominal, so it is clamped
    assert ils.inflationary_ils == 0.0


def test_unknown_open_date_falls_back_to_closing_rate_and_says_so():
    lot = match_lots([_ex(date(2025, 3, 10), -100, 1200, basis=-1001.0, code="C;P")], "s")[0]
    cs = _cs({date(2025, 3, 10): 3.7})
    ils = convert_trade_item(_item(lot), cs)
    assert ils.real_ils == round(198 * 3.7, 2)
    assert ils.note and "תאריך רכישה לא ידוע" in ils.note


def test_accountant_supplied_acquisition_date_enables_the_full_calculation():
    lot = match_lots([_ex(date(2025, 3, 10), -100, 1200, basis=-1001.0, code="C;P")], "s")[0]
    cs = _cs({date(2024, 12, 9): 3.5, date(2025, 3, 10): 3.7})
    ils = convert_trade_item(_item(lot), cs, {"ABC": date(2024, 12, 9)})
    assert ils.nominal_ils == round(1199 * 3.7 - 1001 * 3.5, 2)
    assert ils.buy_rate == 3.5 and ils.note is None


def test_missing_rate_for_the_open_date_degrades_with_a_note_instead_of_failing():
    lot = match_lots([_ex(date(2025, 1, 10), 100, -1000), _ex(date(2025, 3, 10), -100, 1200, code="C;P")], "s")[0]
    cs = _cs({date(2025, 3, 10): 3.7})  # nothing on or before the purchase date
    ils = convert_trade_item(_item(lot), cs)
    assert ils.real_ils == round(198 * 3.7, 2)
    assert ils.note and "חסר שער" in ils.note


def test_nispach_c_reports_real_nominal_and_exempt_totals():
    lot = match_lots([_ex(date(2025, 1, 10), 100, -1000), _ex(date(2025, 3, 10), -100, 1200, code="C;P")], "s")[0]
    cs = _cs({date(2025, 1, 10): 3.6, date(2025, 3, 10): 3.7})
    result = build_nispach_c([_item(lot)], {}, cs)
    assert result.total_gain_ils == 732.6
    assert result.total_nominal_gain_ils == 832.7
    assert result.total_inflationary_exempt_ils == 100.1


# ---- sales total and forex ----

REALIZED_WITH_FOREX = """
Realized & Unrealized Performance Summary
Realized Unrealized
Symbol Cost Adj. S/T Profit S/T Loss L/T Profit L/T Loss Total S/T Profit S/T Loss L/T Profit L/T Loss Total Total Code
Stocks
QQQ 0.00 100.00 0.00 0.00 0.00 100.00 0.00 0.00 0.00 0.00 0.00 100.00
Total Stocks 0.00 100.00 0.00 0.00 0.00 100.00 0.00 0.00 0.00 0.00 0.00 100.00
Forex
ILS 0.00 50.00 0.00 0.00 0.00 50.00 0.00 0.00 0.00 0.00 0.00 50.00
Total Forex 0.00 50.00 0.00 0.00 0.00 50.00 0.00 0.00 0.00 0.00 0.00 50.00
"""


def test_realized_table_rows_are_tagged_with_their_section():
    from app.parsers.ibkr_activity import parse_realized_pnl_text

    trades = parse_realized_pnl_text(REALIZED_WITH_FOREX, "s", 2, date(2025, 12, 31))
    assert {t.symbol: t.asset_class for t in trades} == {"QQQ": "Stocks", "ILS": "Forex"}


def test_forex_profit_is_kept_out_of_the_totals_and_shown_separately():
    stock = Trade(symbol="QQQ", close_date=date(2025, 3, 10), proceeds=0, cost_basis=0, realized_pnl=100.0,
                  holding_term=HoldingTerm.SHORT, source=SRC, asset_class="Stocks")
    forex = Trade(symbol="ILS", close_date=date(2025, 3, 10), proceeds=0, cost_basis=0, realized_pnl=50.0,
                  holding_term=HoldingTerm.SHORT, source=SRC, asset_class="Forex")
    cs = _cs({date(2025, 3, 10): 3.7})
    result = build_nispach_c([_item(stock), _item(forex)], {}, cs)
    assert result.total_gain_ils == 370.0
    assert result.excluded_forex_gain_ils == 185.0
    assert sum(b.item_count for b in result.bracket_totals) == 1


def test_sales_total_is_the_sale_side_cash_of_every_lot_at_its_own_rate():
    long_lot = match_lots([_ex(date(2025, 1, 10), 100, -1000), _ex(date(2025, 3, 10), -100, 1200, code="C;P")], "s")[0]
    short_lot = match_lots(
        [_ex(date(2025, 1, 10), -50, 600, symbol="SSS"), _ex(date(2025, 3, 10), 50, -500, symbol="SSS", code="C;P")], "s"
    )[0]
    cs = _cs({date(2025, 1, 10): 3.6, date(2025, 3, 10): 3.7})
    result = build_nispach_c([_item(long_lot), _item(short_lot)], {"ABC": 999999.0, "SSS": 999999.0}, cs)
    # long: sale on 3/10 (1199 net of commission x 3.7); short: sale on 1/10 (599 x 3.6) -- the buy-back adds nothing
    assert result.total_sale_proceeds_ils == round(1199 * 3.7 + 599 * 3.6, 2)
    assert result.sale_proceeds_is_estimate is False  # the symbol-level estimate is ignored once lots exist


def test_a_short_sale_made_in_a_prior_year_is_not_counted_as_this_years_sale():
    lot = match_lots([_ex(date(2025, 3, 10), 100, -1000, basis=1200.0, code="C;P")], "s")[0]
    assert lot.is_short is True and lot.open_date is None
    cs = _cs({date(2024, 12, 9): 3.5, date(2025, 3, 10): 3.7})
    result = build_nispach_c([_item(lot)], {}, cs, acquisition_dates={"ABC": date(2024, 12, 9)})
    assert result.total_sale_proceeds_ils == 0.0


def test_summary_only_symbols_still_use_the_labelled_estimate():
    summary = Trade(symbol="QQQ", close_date=date(2025, 9, 11), proceeds=0, cost_basis=0, realized_pnl=10.0,
                    holding_term=HoldingTerm.LONG, source=SRC)
    cs = _cs({date(2025, 9, 11): 3.6})
    result = build_nispach_c([_item(summary)], {"QQQ": 5000.0}, cs)
    assert result.total_sale_proceeds_ils == 18000.0
    assert result.sale_proceeds_is_estimate is True
