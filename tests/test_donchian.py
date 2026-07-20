"""Donchian breakout logic, on constructed price paths."""

import numpy as np
import pytest

from cq.context import Context, Series
from cq.core.clock import HOUR_MS
from cq.strategy.donchian import DonchianTrend

DAY0 = 1_609_459_200_000


def series_from(closes):
    n = len(closes)
    values = np.array(closes, dtype=float)
    return Series(
        inst_id="X",
        timeframe="4h",
        ts=np.array([DAY0 + i * 4 * HOUR_MS for i in range(n)], dtype=np.int64),
        open=values,
        high=values,
        low=values,
        close=values,
        volume=np.full(n, 100.0),
    )


def targets_over(closes, entry=5, exit_=3):
    """Run the strategy across a price path, returning the target each bar."""
    strategy = DonchianTrend(entry_lookback=entry, exit_lookback=exit_)
    ctx = Context(series_from(closes))
    out = []
    for i in range(len(closes)):
        ctx.seek(i)
        if i + 1 < strategy.warmup_bars:
            out.append(None)
            continue
        out.append(strategy.on_bar(ctx).target)
    return out


def test_the_channel_excludes_the_current_bar():
    # A close never exceeds its own high, so including the current bar makes
    # the long entry unsatisfiable and the strategy silently never trades.
    rising = [10.0] * 6 + [20.0]
    assert targets_over(rising)[-1] == 1.0


def test_breakout_above_the_entry_channel_goes_long():
    path = [10, 11, 10, 11, 10, 11, 50]
    assert targets_over(path)[-1] == 1.0


def test_breakdown_below_the_entry_channel_goes_short():
    path = [10, 11, 10, 11, 10, 11, 1]
    assert targets_over(path)[-1] == -1.0


def test_a_long_exits_when_the_exit_channel_breaks():
    # Break out, hold, then fall below the 3-bar low.
    path = [10, 11, 10, 11, 10, 11, 50, 51, 52, 1]
    result = targets_over(path)
    assert result[6] == 1.0
    assert result[-1] == 0.0


def test_a_short_exits_when_the_exit_channel_breaks():
    path = [10, 11, 10, 11, 10, 11, 1, 1, 1, 99]
    result = targets_over(path)
    assert result[6] == -1.0
    assert result[-1] == 0.0


def test_a_position_is_held_while_the_trend_continues():
    path = [10, 11, 10, 11, 10, 11, 50, 51, 52, 53, 54]
    result = targets_over(path)
    assert result[6:] == [1.0] * 5


def test_no_position_without_a_breakout():
    path = [10, 11, 10, 11, 10, 11, 10.5, 10.5, 10.5]
    assert set(targets_over(path)[5:]) == {0.0}


def test_exiting_does_not_immediately_reverse():
    # Leaving a long means flat, not short: a re-entry needs its own breakout
    # of the entry channel.
    path = [10, 11, 10, 11, 10, 11, 50, 51, 52, 40]
    result = targets_over(path)
    assert result[-1] == 0.0


def test_warmup_covers_the_lookback_plus_one():
    strategy = DonchianTrend(entry_lookback=120, exit_lookback=60)
    assert strategy.warmup_bars == 121


def test_the_name_records_the_parameters():
    assert DonchianTrend(120, 60).name == "donchian-120-60"


def test_invalid_parameters_are_rejected():
    with pytest.raises(ValueError):
        DonchianTrend(entry_lookback=1)
    with pytest.raises(ValueError):
        DonchianTrend(size=0)


def test_the_strategy_asks_for_no_more_history_than_its_warmup_allows():
    # If it asked for more, Context would raise rather than quietly pad —
    # this pins the two numbers together.
    strategy = DonchianTrend(entry_lookback=120, exit_lookback=60)
    closes = list(np.linspace(10, 20, 200))
    ctx = Context(series_from(closes))
    ctx.seek(strategy.warmup_bars - 1)
    strategy.on_bar(ctx)  # must not raise
