"""DonchianTrend: channel breakout entry/exit, hold in between, warmup, reset.

Also the plumbing check for the strategy interface itself: the end-to-end
case runs the strategy through the real `run_backtest` engine, not just
against a bare `Context`.
"""

import numpy as np
import pytest

from cq.context import Context, LookaheadError, Series
from cq.core.clock import HOUR_MS
from cq.core.types import CostModel, MarketSpec
from cq.engine.loop import run_backtest
from cq.strategy.donchian import DonchianTrend

DAY0 = 1_609_459_200_000
SPOT = MarketSpec("DOGE-USDT", "spot")
FREE = CostModel(fee_bps=0.0, slippage_bps=0.0)


def make_series(closes: list[float], timeframe: str = "1h") -> Series:
    values = np.array(closes, dtype=float)
    n = len(values)
    return Series(
        inst_id="DOGE-USDT",
        timeframe=timeframe,
        ts=np.array([DAY0 + i * HOUR_MS for i in range(n)], dtype=np.int64),
        open=values,
        high=values,
        low=values,
        close=values,
        volume=np.full(n, 100.0),
    )


def test_lookback_must_be_positive():
    with pytest.raises(ValueError):
        DonchianTrend(lookback=0)


def test_warmup_bars_covers_the_channel_plus_the_deciding_bar():
    assert DonchianTrend(lookback=3).warmup_bars == 4


def test_on_bar_raises_before_enough_bars_have_closed():
    strategy = DonchianTrend(lookback=3)
    ctx = Context(make_series([10, 10, 10]))
    ctx.seek(2)
    with pytest.raises(LookaheadError):
        strategy.on_bar(ctx)


def test_breakout_above_the_channel_high_goes_long():
    strategy = DonchianTrend(lookback=3)
    ctx = Context(make_series([10, 10, 10, 15]))
    ctx.seek(3)
    assert strategy.on_bar(ctx).target == 1.0


def test_price_inside_the_channel_holds_the_prior_target():
    strategy = DonchianTrend(lookback=3)
    ctx = Context(make_series([10, 10, 10, 15, 12]))
    ctx.seek(3)
    strategy.on_bar(ctx)  # breaks out long
    ctx.seek(4)
    assert strategy.on_bar(ctx).target == 1.0


def test_breakout_below_the_channel_low_flattens():
    strategy = DonchianTrend(lookback=3)
    ctx = Context(make_series([10, 10, 10, 15, 12, 5]))
    for i in (3, 4):
        ctx.seek(i)
        strategy.on_bar(ctx)
    ctx.seek(5)
    assert strategy.on_bar(ctx).target == 0.0


def test_reset_clears_the_held_target():
    strategy = DonchianTrend(lookback=3)
    ctx = Context(make_series([10, 10, 10, 15, 12]))
    ctx.seek(3)
    strategy.on_bar(ctx)  # breaks out long
    strategy.reset()
    ctx.seek(4)
    assert strategy.on_bar(ctx).target == 0.0


def test_run_backtest_end_to_end_enters_and_exits_through_the_real_engine():
    closes = [10, 10, 10, 10, 10, 11, 12, 13, 20, 19, 18, 17, 5, 6, 6, 6]
    strategy = DonchianTrend(lookback=3)

    result = run_backtest(strategy, make_series(closes), SPOT, 1000.0, costs=FREE)

    assert result.bars == len(closes)
    assert len(result.fills) == 2  # one entry breakout, one exit breakout
    assert result.fills[0].side.name == "BUY"
    assert result.fills[1].side.name == "SELL"
    assert np.isfinite(result.final_equity)
