"""Engine: fill timing, target differencing, protective exits, funding.

The centrepiece is a ten-bar scenario reconciled by hand — every cash figure
below is worked out from the trade, not read off the implementation.
"""

import numpy as np
import pytest

from cq.context import Bar, Context, Series
from cq.core.clock import HOUR_MS
from cq.core.types import CostModel, Intent, MarketSpec, TradingError
from cq.engine.funding import AssumedFunding, NoFunding
from cq.engine.loop import run_backtest
from cq.engine.portfolio import Portfolio
from cq.engine.sim import SimBroker

DAY0 = 1_609_459_200_000
SPOT = MarketSpec("DOGE-USDT", "spot")
SWAP = MarketSpec("DOGE-USDT-SWAP", "swap", max_leverage=3.0)
FREE = CostModel(fee_bps=0.0, slippage_bps=0.0)


def make_series(closes, opens=None, highs=None, lows=None, volumes=None, timeframe="1h"):
    n = len(closes)
    closes = np.array(closes, dtype=float)
    opens = np.array(opens if opens is not None else closes, dtype=float)
    highs = np.array(highs if highs is not None else np.maximum(opens, closes), dtype=float)
    lows = np.array(lows if lows is not None else np.minimum(opens, closes), dtype=float)
    volumes = np.array(volumes if volumes is not None else [100.0] * n, dtype=float)
    step = HOUR_MS
    return Series(
        inst_id="DOGE-USDT",
        timeframe=timeframe,
        ts=np.array([DAY0 + i * step for i in range(n)], dtype=np.int64),
        open=opens,
        high=highs,
        low=lows,
        close=closes,
        volume=volumes,
    )


class Scripted:
    """Returns a preset target for each bar index."""

    def __init__(self, targets, warmup=1, stop=None, take=None):
        self.targets = targets
        self._warmup = warmup
        self.stop = stop
        self.take = take
        self.seen: list[int] = []

    @property
    def name(self):
        return "scripted"

    @property
    def warmup_bars(self):
        return self._warmup

    def on_bar(self, ctx: Context) -> Intent:
        self.seen.append(ctx.index)
        target = self.targets[ctx.index] if ctx.index < len(self.targets) else 0.0
        return Intent(target=target, stop_loss=self.stop, take_profit=self.take)


# ---- fill timing -------------------------------------------------------


def test_decision_on_a_bar_fills_at_the_next_bar_open():
    # Target set while bar 0 is closing; bar 1 opens at 20.0.
    series = make_series(closes=[10, 12, 14], opens=[10, 20, 30])
    result = run_backtest(Scripted([1.0, 1.0, 1.0]), series, SPOT, 1000.0, costs=FREE)

    assert len(result.fills) == 1
    fill = result.fills[0]
    assert fill.ts == DAY0 + HOUR_MS, "filled on bar 1, not bar 0"
    assert fill.price == 20.0, "filled at bar 1's open, not bar 0's close"


def test_a_strategy_never_sees_a_bar_before_it_closes():
    series = make_series(closes=[10, 11, 12, 13])
    strategy = Scripted([0.0, 0.0, 0.0, 0.0])
    run_backtest(strategy, series, SPOT, 1000.0, costs=FREE)
    assert strategy.seen == [0, 1, 2, 3]


def test_warmup_bars_are_not_traded():
    series = make_series(closes=[10, 11, 12, 13, 14])
    strategy = Scripted([1.0] * 5, warmup=3)
    result = run_backtest(strategy, series, SPOT, 1000.0, costs=FREE)

    assert strategy.seen == [2, 3, 4], "no decisions before the warmup completes"
    # First decision on bar 2 fills on bar 3.
    assert result.fills[0].ts == DAY0 + 3 * HOUR_MS


# ---- target differencing ----------------------------------------------


def test_target_returning_to_zero_closes_the_position():
    # The defect this semantics eliminates: the old engine only acted when a
    # signal flipped sign, so 1 -> 0 never closed anything.
    series = make_series(closes=[10, 10, 10, 10], opens=[10, 10, 10, 10])
    result = run_backtest(Scripted([1.0, 0.0, 0.0, 0.0]), series, SPOT, 1000.0, costs=FREE)

    assert len(result.fills) == 2
    assert result.fills[0].side.value == "buy"
    assert result.fills[1].side.value == "sell"
    assert result.portfolio.is_flat


def test_unchanged_target_does_not_retrade():
    series = make_series(closes=[10] * 5, opens=[10] * 5)
    result = run_backtest(Scripted([1.0] * 5), series, SPOT, 1000.0, costs=FREE)
    assert len(result.fills) == 1, "holding a target must not churn"


def test_partial_target_change_trades_only_the_difference():
    series = make_series(closes=[10] * 4, opens=[10] * 4)
    result = run_backtest(Scripted([1.0, 0.5, 0.5, 0.5]), series, SPOT, 1000.0, costs=FREE)

    assert len(result.fills) == 2
    # 100 units bought, then half sold.
    assert result.fills[0].quantity == pytest.approx(100.0)
    assert result.fills[1].quantity == pytest.approx(50.0)


def test_swap_target_can_flip_from_long_to_short_in_one_order():
    series = make_series(closes=[10] * 4, opens=[10] * 4)
    result = run_backtest(Scripted([1.0, -1.0, -1.0, -1.0]), series, SWAP, 1000.0, costs=FREE)

    assert result.portfolio.is_short
    # 100 long -> 100 short is a single 200-unit sale.
    assert result.fills[1].quantity == pytest.approx(200.0)


def test_spot_short_target_raises_rather_than_becoming_flat():
    series = make_series(closes=[10] * 3, opens=[10] * 3)
    with pytest.raises(TradingError, match="silently change"):
        run_backtest(Scripted([-1.0, -1.0, -1.0]), series, SPOT, 1000.0, costs=FREE)


# ---- zero volume -------------------------------------------------------


def test_no_fill_on_a_zero_volume_bar():
    # OKX printed nine hours of flat synthetic bars on 2022-12-18. Filling
    # against them invents trades that could not have happened.
    series = make_series(closes=[10, 10, 10], opens=[10, 10, 10], volumes=[100, 0, 100])
    result = run_backtest(Scripted([1.0, 1.0, 1.0]), series, SPOT, 1000.0, costs=FREE)

    assert result.fills[0].ts == DAY0 + 2 * HOUR_MS, "deferred past the dead bar"
    assert any("zero-volume" in r.reason for r in result.rejections)


def test_zero_volume_rejection_is_recorded_not_swallowed():
    series = make_series(closes=[10, 10], opens=[10, 10], volumes=[100, 0])
    result = run_backtest(Scripted([1.0, 1.0]), series, SPOT, 1000.0, costs=FREE)

    assert result.fills == []
    assert len(result.rejections) == 1
    assert result.rejections[0].ts == DAY0 + HOUR_MS


# ---- protective exits --------------------------------------------------


def test_stop_triggers_off_the_low_not_the_close():
    # Bar 2 dips to 8 intrabar and recovers to close at 11. A stop at 9 was hit.
    series = make_series(
        closes=[10, 10, 11], opens=[10, 10, 10], highs=[10, 10, 12], lows=[10, 10, 8]
    )
    result = run_backtest(
        Scripted([1.0, 1.0, 1.0], stop=9.0), series, SPOT, 1000.0, costs=FREE
    )

    exits = [f for f in result.fills if f.reason == "stop loss"]
    assert len(exits) == 1
    assert exits[0].price == 9.0


def test_when_a_bar_touches_both_levels_the_stop_wins():
    # Tick order within a bar is unknowable; taking the favourable one is how
    # a backtest quietly beats the market it models.
    series = make_series(
        closes=[10, 10, 10], opens=[10, 10, 10], highs=[10, 10, 20], lows=[10, 10, 5]
    )
    result = run_backtest(
        Scripted([1.0, 1.0, 1.0], stop=9.0, take=15.0), series, SPOT, 1000.0, costs=FREE
    )

    exits = [f for f in result.fills if f.reason in ("stop loss", "take profit")]
    assert exits[0].reason == "stop loss"


def test_take_profit_triggers_off_the_high():
    series = make_series(
        closes=[10, 10, 11], opens=[10, 10, 10], highs=[10, 10, 16], lows=[10, 10, 10]
    )
    result = run_backtest(
        Scripted([1.0, 1.0, 1.0], take=15.0), series, SPOT, 1000.0, costs=FREE
    )
    exits = [f for f in result.fills if f.reason == "take profit"]
    assert exits[0].price == 15.0


def test_short_stop_triggers_off_the_high():
    series = make_series(
        closes=[10, 10, 10], opens=[10, 10, 10], highs=[10, 10, 13], lows=[10, 10, 10]
    )
    result = run_backtest(
        Scripted([-1.0, -1.0, -1.0], stop=12.0), series, SWAP, 1000.0, costs=FREE
    )
    exits = [f for f in result.fills if f.reason == "stop loss"]
    assert exits[0].price == 12.0


# ---- costs -------------------------------------------------------------


def test_slippage_and_fees_are_charged_on_both_sides():
    series = make_series(closes=[10] * 4, opens=[10] * 4)
    costs = CostModel(fee_bps=10.0, slippage_bps=5.0)
    result = run_backtest(Scripted([1.0, 0.0, 0.0, 0.0]), series, SPOT, 1000.0, costs=costs)

    entry, exit_ = result.fills
    assert entry.price == pytest.approx(10.005)  # bought up
    assert exit_.price == pytest.approx(9.995)  # sold down
    assert result.total_return < 0, "a flat market must lose exactly the costs"


# ---- funding -----------------------------------------------------------


def test_swap_funding_accrues_over_a_hold():
    # 24 hourly bars = three settlements a day at 00:00, 08:00, 16:00 UTC.
    series = make_series(closes=[10] * 25, opens=[10] * 25)
    model = AssumedFunding(rate=0.0001)
    result = run_backtest(
        Scripted([1.0] * 25), series, SWAP, 1000.0, costs=FREE, funding=model
    )

    assert len(result.funding_payments) == 3
    assert result.portfolio.funding_paid > 0
    assert result.total_return < 0, "funding must show up as drag on a flat market"


def test_funding_off_leaves_the_result_untouched():
    series = make_series(closes=[10] * 25, opens=[10] * 25)
    result = run_backtest(
        Scripted([1.0] * 25), series, SWAP, 1000.0, costs=FREE, funding=NoFunding()
    )
    assert result.funding_payments == []
    assert result.total_return == pytest.approx(0.0)


def test_spot_never_accrues_funding():
    series = make_series(closes=[10] * 25, opens=[10] * 25)
    result = run_backtest(
        Scripted([1.0] * 25), series, SPOT, 1000.0, costs=FREE, funding=AssumedFunding(0.01)
    )
    assert result.funding_payments == []


def test_the_run_records_which_funding_assumption_produced_it():
    series = make_series(closes=[10] * 3, opens=[10] * 3)
    off = run_backtest(Scripted([0.0] * 3), series, SWAP, 1000.0, funding=NoFunding())
    assumed = run_backtest(
        Scripted([0.0] * 3), series, SWAP, 1000.0, funding=AssumedFunding(0.0001)
    )

    assert "upper bound" in off.funding_label
    assert "assumption" in assumed.funding_label


# ---- the hand-reconciled scenario --------------------------------------


def test_ten_bar_scenario_reconciles_to_hand_computed_cash():
    """Ten bars, worked out on paper.

    opens:  10, 10, 12, 12, 12, 12, 15, 15, 15, 15
    target:  bar0 -> 1.0 (fills bar1 @10), bar5 -> 0.0 (fills bar6 @15)

    Buy  100 units @ 10.00 -> cash 1000 - 1000 = 0,     qty 100
    Sell 100 units @ 15.00 -> cash 0 + 1500   = 1500,   qty 0
    Realised 100 * (15 - 10) = 500. No fees, no slippage, no funding.
    """
    opens = [10, 10, 12, 12, 12, 12, 15, 15, 15, 15]
    series = make_series(closes=opens, opens=opens)
    targets = [1.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0]

    result = run_backtest(Scripted(targets), series, SPOT, 1000.0, costs=FREE)

    assert len(result.fills) == 2
    buy, sell = result.fills
    assert (buy.price, buy.quantity) == (10.0, 100.0)
    assert (sell.price, sell.quantity) == (15.0, 100.0)

    p = result.portfolio
    assert p.cash == pytest.approx(1500.0)
    assert p.realized_pnl == pytest.approx(500.0)
    assert p.fees_paid == 0.0
    assert p.is_flat
    assert result.final_equity == pytest.approx(1500.0)
    assert result.total_return == pytest.approx(0.5)

    # Equity marked each bar: flat at 1000 until the buy, then marked to close.
    assert result.equity[0] == pytest.approx(1000.0)
    assert result.equity[1] == pytest.approx(1000.0)  # bought at 10, closes at 10
    assert result.equity[2] == pytest.approx(1200.0)  # 100 units at 12
    assert result.equity[-1] == pytest.approx(1500.0)


# ---- broker units ------------------------------------------------------


def test_sizing_is_the_difference_from_what_is_held():
    broker = SimBroker(SPOT, FREE)
    portfolio = Portfolio(SPOT, 1000.0)
    assert broker.quantity_for_target(1.0, 10.0, 1000.0, held=0.0) == pytest.approx(100.0)
    assert broker.quantity_for_target(1.0, 10.0, 1000.0, held=60.0) == pytest.approx(40.0)
    assert broker.quantity_for_target(0.0, 10.0, 1000.0, held=60.0) == pytest.approx(-60.0)
    assert portfolio.is_flat


def test_holding_a_full_target_does_not_churn_on_floating_point_dust():
    # A fully invested position never re-derives to exactly what is held, so
    # without a floor every bar emits a crumb-sized order. Buy-and-hold over
    # real DOGE produced 877 "trades" this way — enough to bleed fees and to
    # make trade count meaningless for bootstrap and DSR.
    rising = [10.0 * (1.01**i) for i in range(200)]
    series = make_series(closes=rising, opens=rising)

    result = run_backtest(Scripted([1.0] * 200), series, SPOT, 1000.0, costs=FREE)

    assert len(result.fills) == 1, f"expected one entry, got {len(result.fills)}"


def test_a_genuine_rebalance_is_still_traded():
    # The dust floor must not swallow a real target change.
    series = make_series(closes=[10] * 5, opens=[10] * 5)
    result = run_backtest(Scripted([1.0, 0.9, 0.9, 0.9, 0.9]), series, SPOT, 1000.0, costs=FREE)

    assert len(result.fills) == 2
    assert result.fills[1].quantity == pytest.approx(10.0)


def test_order_below_minimum_notional_is_rejected_not_rounded_up():
    spec = MarketSpec("X", "spot", min_notional=100.0)
    broker = SimBroker(spec, FREE)
    portfolio = Portfolio(spec, 1000.0)
    bar = Bar(DAY0, open=10.0, high=10.0, low=10.0, close=10.0, volume=100.0)

    fill = broker.execute(portfolio, bar, delta=1.0)
    assert fill is None
    assert broker.rejections[-1].reason == "below minimum notional"
