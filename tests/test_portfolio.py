"""Portfolio accounting, reconciled by hand.

Every expected number here is worked out from the trade, not read back from
the implementation. The previous system's PnL was self-consistent and wrong.
"""

import pytest

from cq.core.types import CostModel, Fill, MarketSpec, Side, TradingError
from cq.engine.portfolio import Portfolio

SPOT = MarketSpec("DOGE-USDT", "spot")
SWAP = MarketSpec("DOGE-USDT-SWAP", "swap", max_leverage=3.0)


def fill(side, quantity, price, fee=0.0, ts=0):
    return Fill(ts=ts, inst_id="X", side=side, quantity=quantity, price=price, fee=fee)


def buy(quantity, price, fee=0.0, ts=0):
    return fill(Side.BUY, quantity, price, fee, ts)


def sell(quantity, price, fee=0.0, ts=0):
    return fill(Side.SELL, quantity, price, fee, ts)


# ---- spot --------------------------------------------------------------


def test_spot_buy_converts_cash_into_the_asset():
    p = Portfolio(SPOT, initial_cash=1000.0)
    p.apply(buy(100, 2.0, fee=0.2))

    # 100 * 2.0 = 200 spent, plus 0.2 fee.
    assert p.cash == pytest.approx(799.8)
    assert p.quantity == 100
    assert p.avg_entry == 2.0
    # Equity at cost is the starting cash less the fee.
    assert p.equity(2.0) == pytest.approx(999.8)


def test_spot_round_trip_reconciles_to_the_hand_computed_result():
    p = Portfolio(SPOT, initial_cash=1000.0)
    p.apply(buy(100, 2.0, fee=0.2))
    p.apply(sell(100, 2.5, fee=0.25))

    # Gross: 100 * (2.5 - 2.0) = 50. Fees: 0.45. Net: 49.55.
    assert p.realized_pnl == pytest.approx(50.0)
    assert p.fees_paid == pytest.approx(0.45)
    assert p.net_pnl == pytest.approx(49.55)
    assert p.cash == pytest.approx(1049.55)
    assert p.is_flat
    assert p.equity(2.5) == pytest.approx(1049.55)


def test_spot_losing_trade_is_recorded_as_a_loss_in_both_units():
    # The exact defect from the old system: a losing trade booked as a large
    # positive absolute PnL because sale proceeds were mistaken for profit.
    p = Portfolio(SPOT, initial_cash=1000.0)
    p.apply(buy(100, 1.0))
    p.apply(sell(100, 0.9))

    assert p.realized_pnl == pytest.approx(-10.0)
    assert p.net_pnl < 0
    assert p.cash == pytest.approx(990.0)
    assert p.equity(0.9) < p.initial_cash


def test_partial_exit_leaves_the_cost_basis_alone():
    p = Portfolio(SPOT, initial_cash=1000.0)
    p.apply(buy(100, 2.0))
    p.apply(sell(40, 3.0))

    assert p.quantity == 60
    assert p.avg_entry == 2.0, "selling part of a position does not reprice the rest"
    assert p.realized_pnl == pytest.approx(40.0)  # 40 * (3.0 - 2.0)
    assert p.unrealized_pnl(3.0) == pytest.approx(60.0)  # 60 * 1.0


def test_adding_to_a_position_averages_the_cost_basis():
    p = Portfolio(SPOT, initial_cash=1000.0)
    p.apply(buy(100, 2.0))
    p.apply(buy(100, 3.0))

    assert p.quantity == 200
    assert p.avg_entry == pytest.approx(2.5)
    assert p.realized_pnl == 0.0


def test_spot_cannot_sell_more_than_the_strategy_owns():
    # The P0 defect: spot exit sold the account's entire free balance, which
    # could include coins a human or another strategy put there.
    p = Portfolio(SPOT, initial_cash=1000.0)
    p.apply(buy(50, 2.0))

    with pytest.raises(TradingError, match="not ours to sell"):
        p.apply(sell(80, 2.0))

    assert p.quantity == 50, "the rejected sale must not have moved anything"


def test_spot_cannot_go_short():
    p = Portfolio(SPOT, initial_cash=1000.0)
    with pytest.raises(TradingError):
        p.apply(sell(10, 2.0))


def test_selling_exactly_what_is_held_is_allowed():
    p = Portfolio(SPOT, initial_cash=1000.0)
    p.apply(buy(50, 2.0))
    p.apply(sell(50, 2.0))
    assert p.is_flat


# ---- swap --------------------------------------------------------------


def test_swap_position_does_not_consume_cash_beyond_fees():
    p = Portfolio(SWAP, initial_cash=1000.0)
    p.apply(buy(100, 2.0, fee=0.2))

    assert p.cash == pytest.approx(999.8), "a swap is collateralised, not bought"
    assert p.quantity == 100
    assert p.equity(2.0) == pytest.approx(999.8)
    assert p.equity(2.5) == pytest.approx(1049.8)  # +100 * 0.5 unrealised


def test_swap_short_profits_when_price_falls():
    p = Portfolio(SWAP, initial_cash=1000.0)
    p.apply(sell(100, 2.0))

    assert p.is_short
    assert p.quantity == -100
    assert p.unrealized_pnl(1.5) == pytest.approx(50.0)  # -100 * (1.5 - 2.0)

    p.apply(buy(100, 1.5))
    assert p.realized_pnl == pytest.approx(50.0)
    assert p.cash == pytest.approx(1050.0)


def test_swap_flip_closes_then_opens_at_the_new_price():
    p = Portfolio(SWAP, initial_cash=1000.0)
    p.apply(buy(100, 2.0))
    p.apply(sell(150, 3.0))  # close +100, open -50

    assert p.realized_pnl == pytest.approx(100.0)  # 100 * (3.0 - 2.0)
    assert p.quantity == -50
    assert p.avg_entry == 3.0, "the remainder is a fresh position at the fill price"


def test_swap_equity_reconciles_across_a_full_cycle():
    p = Portfolio(SWAP, initial_cash=1000.0)
    p.apply(buy(100, 2.0, fee=0.2))
    p.apply(sell(100, 2.4, fee=0.24))

    # Gross 40.0, fees 0.44, no funding.
    assert p.equity(2.4) == pytest.approx(1000.0 + 40.0 - 0.44)
    assert p.equity(2.4) == pytest.approx(p.initial_cash + p.net_pnl)


# ---- funding -----------------------------------------------------------


def test_long_pays_funding_when_the_rate_is_positive():
    p = Portfolio(SWAP, initial_cash=1000.0)
    p.apply(buy(1000, 0.1))  # 100 USDT notional

    payment = p.apply_funding(ts=1, rate=0.0001, mark_price=0.1)

    assert payment.amount == pytest.approx(0.01)  # 100 * 0.0001
    assert p.cash == pytest.approx(999.99)
    assert p.funding_paid == pytest.approx(0.01)
    assert p.net_pnl == pytest.approx(-0.01)


def test_short_receives_funding_when_the_rate_is_positive():
    p = Portfolio(SWAP, initial_cash=1000.0)
    p.apply(sell(1000, 0.1))

    payment = p.apply_funding(ts=1, rate=0.0001, mark_price=0.1)

    assert payment.amount == pytest.approx(-0.01)
    assert p.cash == pytest.approx(1000.01)


def test_funding_accumulates_over_a_multi_period_hold():
    # A 4h trend strategy holding for days pays this eight times a day; the
    # cumulative drag is what an off-funding backtest hides.
    p = Portfolio(SWAP, initial_cash=1000.0)
    p.apply(buy(1000, 0.1))
    for i in range(9):  # three days at 3 settlements a day
        p.apply_funding(ts=i, rate=0.0001, mark_price=0.1)

    assert p.funding_paid == pytest.approx(0.09)
    assert p.cash == pytest.approx(999.91)


def test_flat_position_pays_no_funding():
    p = Portfolio(SWAP, initial_cash=1000.0)
    payment = p.apply_funding(ts=1, rate=0.01, mark_price=0.1)
    assert payment.amount == 0.0
    assert p.cash == 1000.0


def test_spot_has_no_funding():
    p = Portfolio(SPOT, initial_cash=1000.0)
    with pytest.raises(TradingError, match="no funding"):
        p.apply_funding(ts=1, rate=0.0001, mark_price=1.0)


# ---- market spec -------------------------------------------------------


def test_spot_rejects_a_short_target_instead_of_clamping_it():
    # Clamping would let a long/short strategy silently backtest long-only.
    with pytest.raises(TradingError, match="silently change"):
        SPOT.validate_target(-1.0)


def test_swap_accepts_a_short_target():
    SWAP.validate_target(-1.0)


def test_target_beyond_max_leverage_is_rejected():
    with pytest.raises(TradingError, match="leverage"):
        SWAP.validate_target(4.0)
    with pytest.raises(TradingError, match="leverage"):
        SPOT.validate_target(1.5)


def test_spot_cannot_be_configured_with_leverage():
    with pytest.raises(ValueError, match="cannot be leveraged"):
        MarketSpec("X", "spot", max_leverage=2.0)


def test_quantity_rounds_towards_zero():
    spec = MarketSpec("X", "spot", lot_size=0.1)
    assert spec.round_quantity(1.29) == pytest.approx(1.2)
    assert spec.round_quantity(-1.29) == pytest.approx(-1.2)


def test_a_quantity_already_on_the_lot_grid_survives_rounding():
    # 0.3 is not representable in binary and `0.3 / 0.1` evaluates to
    # 2.9999..., so flooring turned an exactly tradable 0.3 into 0.2 and threw
    # away a third of the order.
    spec = MarketSpec("X", "spot", lot_size=0.1)
    for quantity in (0.3, 0.7, 2.9, 1.1, 70.7):
        assert spec.round_quantity(quantity) == pytest.approx(quantity)


def test_rounding_still_never_exceeds_what_was_asked_for():
    spec = MarketSpec("X", "spot", lot_size=0.1)
    for quantity in (0.29, 1.99, 0.35, 12.34):
        assert abs(spec.round_quantity(quantity)) <= abs(quantity)


def test_rounded_quantities_are_free_of_float_noise():
    # `28 * 0.1` is 2.8000000000000003, which then fails equality checks
    # against the position it is supposed to match.
    spec = MarketSpec("X", "spot", lot_size=0.1)
    assert repr(spec.round_quantity(2.9)) == "2.9"
    assert repr(spec.round_quantity(0.7)) == "0.7"
    # Never rounds up past what was asked for.
    assert abs(spec.round_quantity(1.99)) <= 1.99


# ---- cost model --------------------------------------------------------


def test_slippage_always_moves_against_the_taker():
    costs = CostModel(fee_bps=10.0, slippage_bps=5.0)
    assert costs.fill_price(100.0, Side.BUY) == pytest.approx(100.05)
    assert costs.fill_price(100.0, Side.SELL) == pytest.approx(99.95)


def test_fee_is_charged_on_absolute_notional():
    costs = CostModel(fee_bps=10.0)
    assert costs.fee(1000.0) == pytest.approx(1.0)
    assert costs.fee(-1000.0) == pytest.approx(1.0)
