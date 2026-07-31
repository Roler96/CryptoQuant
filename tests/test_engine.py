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


def test_initial_intent_can_build_a_benchmark_position_at_the_first_open():
    series = make_series(closes=[10, 12], opens=[10, 20])

    result = run_backtest(
        Scripted([1.0, 1.0]),
        series,
        SPOT,
        1000.0,
        costs=FREE,
        initial_intent=Intent(target=1.0, reason="buy-and-hold"),
    )

    assert len(result.fills) == 1
    assert result.fills[0].ts == DAY0
    assert result.fills[0].price == 10.0
    assert result.transactions[0].signal_time is None


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


def test_evaluation_start_primes_strategy_but_only_scores_and_trades_evaluation():
    series = make_series(closes=[10, 10, 10, 10, 10])
    strategy = Scripted([0.0, 0.0, 1.0, 1.0, 1.0])

    result = run_backtest(
        strategy,
        series,
        SPOT,
        1000.0,
        costs=FREE,
        evaluation_start_ms=DAY0 + 3 * HOUR_MS,
    )

    assert result.timestamps == [DAY0 + 3 * HOUR_MS, DAY0 + 4 * HOUR_MS]
    assert result.bars == 2
    assert result.fills[0].ts == DAY0 + 3 * HOUR_MS
    assert result.transactions[0].signal_time == DAY0 + 3 * HOUR_MS


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


def test_transaction_ledger_captures_sizing_costs_and_account_transition():
    series = make_series(closes=[10, 10], opens=[10, 10])
    costs = CostModel(fee_bps=10.0, slippage_bps=5.0)

    result = run_backtest(Scripted([1.0, 1.0]), series, SPOT, 1000.0, costs=costs)

    record = result.transactions[0]
    assert record.status == "filled"
    assert record.signal_time == DAY0 + HOUR_MS
    assert record.execution_time == DAY0 + HOUR_MS
    assert record.requested_quantity > 0
    assert record.filled_quantity == result.fills[0].quantity
    assert record.reference_price == 10.0
    assert record.execution_price == pytest.approx(10.005)
    assert record.cash_after < record.cash_before
    assert record.position_after > record.position_before
    assert record.fee == result.fills[0].fee
    assert record.slippage_cost > 0
    assert record.account_change < 0


def test_rejected_order_is_present_in_transaction_ledger():
    series = make_series(closes=[10, 10], volumes=[100, 0])

    result = run_backtest(Scripted([1.0, 1.0]), series, SPOT, 1000.0, costs=FREE)

    record = result.transactions[0]
    assert record.status == "rejected"
    assert record.rejection_reason == "zero-volume bar: no trade was possible"
    assert record.filled_quantity == 0.0
    assert record.cash_after == record.cash_before
    assert record.position_after == record.position_before


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
    assert len(result.account_events) == len(result.funding_payments)
    event = result.account_events[0]
    assert event.event_type == "funding"
    assert event.cash_after == pytest.approx(event.cash_before - event.amount)


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

    assert "omitted" in off.funding_label
    assert "assumption" in assumed.funding_label


def test_funding_inside_a_bar_is_charged_to_the_position_the_bar_ended_with():
    # Daily bars, one settlement grid of 00:00/08:00/16:00. An entry filling
    # at 00:00 held through 08:00 and 16:00 and owes both. Charging every
    # settlement in the bar before the bar's own order made the entry free.
    daily = make_series(closes=[10] * 3, opens=[10] * 3, timeframe="1d")
    daily = Series(
        inst_id="DOGE-USDT",
        timeframe="1d",
        ts=np.array([DAY0 + i * 24 * HOUR_MS for i in range(3)], dtype=np.int64),
        open=daily.open,
        high=daily.high,
        low=daily.low,
        close=daily.close,
        volume=daily.volume,
    )
    result = run_backtest(
        Scripted([1.0, 1.0, 1.0]), daily, SWAP, 1000.0, costs=FREE,
        funding=AssumedFunding(0.0001),
    )

    # Bar 1 opens at 00:00 and the entry fills there; 08:00 and 16:00 follow.
    paid_on_entry_day = [p for p in result.funding_payments if p.ts < DAY0 + 2 * 24 * HOUR_MS]
    assert len(paid_on_entry_day) == 2
    assert all(p.ts > DAY0 + 24 * HOUR_MS for p in paid_on_entry_day)


def test_an_exit_at_the_open_is_not_charged_for_the_rest_of_the_bar():
    # The mirror image: a position closed at 00:00 held through none of the
    # day's remaining settlements and owes nothing for them.
    ts = np.array([DAY0 + i * 24 * HOUR_MS for i in range(4)], dtype=np.int64)
    values = np.array([10.0] * 4)
    daily = Series(
        inst_id="DOGE-USDT",
        timeframe="1d",
        ts=ts,
        open=values,
        high=values,
        low=values,
        close=values,
        volume=np.array([100.0] * 4),
    )
    result = run_backtest(
        Scripted([1.0, 0.0, 0.0, 0.0]), daily, SWAP, 1000.0, costs=FREE,
        funding=AssumedFunding(0.0001),
    )

    # Entry fills on bar 1 (00:00 day 1), exit fills on bar 2 (00:00 day 2).
    # Owed: day 1's 08:00 and 16:00, and day 2's 00:00 — that last one settles
    # at the very instant of the exit, and funding at a bar's open is charged
    # to the position carried in. Not owed: day 2's 08:00 and 16:00, which the
    # account had already left. Charging those was the defect.
    assert [p.ts for p in result.funding_payments] == [
        DAY0 + 24 * HOUR_MS + 8 * HOUR_MS,
        DAY0 + 24 * HOUR_MS + 16 * HOUR_MS,
        DAY0 + 48 * HOUR_MS,
    ]


def test_settlements_inside_a_data_gap_are_still_charged():
    # Missing bars are missing data, not a holiday from funding. Enumerating
    # settlements per bar skipped every one that fell in the hole.
    ts = np.array([DAY0, DAY0 + HOUR_MS, DAY0 + 25 * HOUR_MS], dtype=np.int64)
    values = np.array([10.0, 10.0, 10.0])
    gapped = Series(
        inst_id="DOGE-USDT",
        timeframe="1h",
        ts=ts,
        open=values,
        high=values,
        low=values,
        close=values,
        volume=np.array([100.0] * 3),
    )
    result = run_backtest(
        Scripted([1.0, 1.0, 1.0]), gapped, SWAP, 1000.0, costs=FREE,
        funding=AssumedFunding(0.0001),
    )

    # The 23-hour hole after 01:00 contains 08:00, 16:00 and 00:00.
    assert len(result.funding_payments) == 3


# ---- gaps through a level ----------------------------------------------


def test_a_stop_gapped_through_fills_at_the_open_not_at_the_level():
    # Bar 2 opens at 5 and never trades above 6. A stop at 9 cannot fill at 9:
    # that price does not occur anywhere in the bar.
    series = make_series(
        closes=[10, 10, 5.5], opens=[10, 10, 5], highs=[10, 10, 6], lows=[10, 10, 5]
    )
    result = run_backtest(
        Scripted([1.0, 1.0, 1.0], stop=9.0), series, SPOT, 1000.0, costs=FREE
    )

    exits = [f for f in result.fills if f.reason == "stop loss"]
    assert exits[0].price == 5.0


def test_a_short_stop_gapped_through_fills_at_the_open():
    series = make_series(
        closes=[10, 10, 20], opens=[10, 10, 21], highs=[10, 10, 22], lows=[10, 10, 20]
    )
    result = run_backtest(
        Scripted([-1.0, -1.0, -1.0], stop=12.0), series, SWAP, 1000.0, costs=FREE
    )

    exits = [f for f in result.fills if f.reason == "stop loss"]
    assert exits[0].price == 21.0


def test_a_take_profit_gapped_through_fills_at_the_open_too():
    # The same rule, and here it runs in the holder's favour: a limit sell at
    # 15 in a market that opened at 18 is filled at 18.
    series = make_series(
        closes=[10, 10, 18], opens=[10, 10, 18], highs=[10, 10, 19], lows=[10, 10, 17]
    )
    result = run_backtest(
        Scripted([1.0, 1.0, 1.0], take=15.0), series, SPOT, 1000.0, costs=FREE
    )

    exits = [f for f in result.fills if f.reason == "take profit"]
    assert exits[0].price == 18.0


def test_a_level_reached_within_the_bar_still_fills_at_the_level():
    # The gap rule must not disturb the ordinary case.
    series = make_series(
        closes=[10, 10, 11], opens=[10, 10, 10], highs=[10, 10, 12], lows=[10, 10, 8]
    )
    result = run_backtest(
        Scripted([1.0, 1.0, 1.0], stop=9.0), series, SPOT, 1000.0, costs=FREE
    )
    stopped = next(f for f in result.fills if f.reason == "stop loss")
    assert stopped.price == 9.0


# ---- liquidation -------------------------------------------------------


LEVERED = MarketSpec("DOGE-USDT-SWAP", "swap", max_leverage=3.0, maintenance_margin_rate=0.005)


def test_a_levered_position_is_liquidated_rather_than_carried_negative():
    # 3x long from 10. A fall to 6 is -40% on the price and -120% on the
    # account: without a liquidation the position simply continues, and the
    # recovery to 12 hands back money that was already gone.
    series = make_series(
        closes=[10, 10, 6, 12], opens=[10, 10, 9, 12], highs=[10, 10, 9, 12],
        lows=[10, 10, 6, 12],
    )
    result = run_backtest(
        Scripted([3.0, 3.0, 3.0, 3.0]), series, LEVERED, 1000.0, costs=FREE
    )

    assert [f.reason for f in result.fills if f.reason == "liquidation"]
    assert min(result.equity) >= 0.0, "equity must never pass through negative"
    # Carried through the fall, the position would have recovered to 1,600 on
    # bar 3. It cannot: the margin was gone at 6.7 and the account with it.
    assert result.final_equity < 50.0


def test_a_stop_above_the_liquidation_price_gets_out_first():
    # The point of a stop. Resolving the two by precedence rather than by
    # price would report a liquidation the account never suffered.
    series = make_series(
        closes=[10, 10, 6], opens=[10, 10, 9.8], highs=[10, 10, 9.8], lows=[10, 10, 6]
    )
    result = run_backtest(
        Scripted([3.0, 3.0, 3.0], stop=9.5), series, LEVERED, 1000.0, costs=FREE
    )

    reasons = [f.reason for f in result.fills if f.reason]
    assert reasons == ["stop loss"]


def test_an_unlevered_swap_is_not_liquidated_by_an_ordinary_drawdown():
    # 1x long: a 40% fall is a 40% drawdown, not a margin call.
    series = make_series(closes=[10, 10, 6, 9], opens=[10, 10, 6, 9])
    result = run_backtest(
        Scripted([1.0, 1.0, 1.0, 1.0]), series, SWAP, 1000.0, costs=FREE
    )

    assert not [f for f in result.fills if f.reason == "liquidation"]
    assert result.final_equity == pytest.approx(900.0)


def test_spot_is_never_liquidated():
    with pytest.raises(ValueError, match="cannot be liquidated"):
        MarketSpec("DOGE-USDT", "spot", maintenance_margin_rate=0.005)


# ---- spot buying power -------------------------------------------------


def test_a_full_weight_spot_buy_does_not_overdraw_the_account():
    # Buying `equity / price` units and then paying fees out of a balance with
    # nothing left in it is a margin loan on a market that does not lend.
    series = make_series(closes=[100] * 3, opens=[100] * 3)
    costs = CostModel(fee_bps=10.0, slippage_bps=5.0)
    result = run_backtest(Scripted([1.0] * 3), series, SPOT, 10_000.0, costs=costs)

    assert result.portfolio.cash >= 0.0
    assert result.portfolio.quantity > 0


def test_buying_without_the_cash_to_pay_for_it_raises():
    spec = MarketSpec("X", "spot")
    portfolio = Portfolio(spec, 100.0)
    broker = SimBroker(spec, FREE)
    bar = Bar(DAY0, open=10.0, high=10.0, low=10.0, close=10.0, volume=100.0)

    with pytest.raises(TradingError, match="cannot borrow"):
        broker.execute(portfolio, bar, delta=20.0)


# ---- strategy state ----------------------------------------------------


def test_a_reused_strategy_starts_each_run_flat():
    # Real strategies remember their target, and instances get reused across
    # splits and parameter sweeps. Without a reset, run two opens holding run
    # one's position and prints an entry no breakout ever triggered.
    class Sticky:
        """Goes long once and stays long — enough to carry state across runs."""

        name = "sticky"
        warmup_bars = 1

        def __init__(self):
            self._target = 0.0

        def reset(self) -> None:
            self._target = 0.0

        def on_bar(self, ctx):
            if self._target == 0.0 and float(ctx.close(1)[-1]) > 15.0:
                self._target = 1.0
            return Intent(target=self._target)

    strategy = Sticky()

    breakout = make_series(closes=[10, 10, 10, 10, 20, 20], opens=[10, 10, 10, 10, 20, 20])
    first = run_backtest(strategy, breakout, SPOT, 1000.0, costs=FREE)
    assert first.fills, "the first run must end holding, or this proves nothing"
    assert first.portfolio.quantity > 0

    # A flat market: no channel is ever broken, so nothing should be bought.
    quiet = make_series(closes=[10] * 6, opens=[10] * 6)
    second = run_backtest(strategy, quiet, SPOT, 1000.0, costs=FREE)

    assert second.fills == [], "run two traded on state left over from run one"


def test_a_strategy_without_a_reset_still_runs():
    # `reset` is optional: the loop must not require every strategy to have
    # one just because some carry state.
    class Stateless:
        name = "stateless"
        warmup_bars = 1

        def on_bar(self, ctx):
            return Intent(target=1.0)

    series = make_series(closes=[10] * 4, opens=[10] * 4)
    assert run_backtest(Stateless(), series, SPOT, 1000.0, costs=FREE).fills


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
    size = broker.quantity_for_target
    assert size(1.0, 10.0, 1000.0, held=0.0, cash=1000.0) == pytest.approx(100.0)
    assert size(1.0, 10.0, 1000.0, held=60.0, cash=400.0) == pytest.approx(40.0)
    assert size(0.0, 10.0, 1000.0, held=60.0, cash=400.0) == pytest.approx(-60.0)
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
