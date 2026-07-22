from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from cq.context import Context, Series
from cq.core.types import CostModel, MarketSpec, Sizing
from cq.engine.loop import run_backtest
from cq.research.metrics import position_spans
from cq.research.split import to_ms
from research.explore_doge_weekly_seasonality import (
    DogeWeeklySeasonality,
    WeeklySeasonalityParams,
)

DAY_MS = 24 * 60 * 60 * 1000
# 2021-01-04 is a Monday, so bar i of a daily series from here opens on
# weekday i % 7 (0 = Monday).
MONDAY = "2021-01-04"


def _daily_series(n_days: int, closes: list[float] | None = None) -> Series:
    start = to_ms(MONDAY)
    ts = start + np.arange(n_days, dtype=np.int64) * DAY_MS
    close = (
        np.full(n_days, 100.0)
        if closes is None
        else np.asarray(closes, dtype=float)
    )
    return Series(
        inst_id="DOGE-USDT",
        timeframe="1d",
        ts=ts,
        open=close,
        high=close * 1.001,
        low=close * 0.999,
        close=close,
        volume=np.full(n_days, 100.0),
    )


def _targets(strategy: DogeWeeklySeasonality, series: Series) -> list[float]:
    ctx = Context(series)
    out: list[float] = []
    for index in range(len(series)):
        ctx.seek(index)
        out.append(strategy.on_bar(ctx).target)
    return out


def test_target_tracks_the_next_bar_weekday() -> None:
    # A full week from Monday. on_bar at bar i decides for bar i+1, so the
    # decided weekday sequence over bars 0..6 is Tue,Wed,Thu,Fri,Sat,Sun,Mon.
    series = _daily_series(7)
    targets = _targets(DogeWeeklySeasonality(), series)

    # Tue,Wed,Thu,Fri are held (0..4), Sat,Sun are cash, then Mon is held again.
    assert targets == [1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 1.0]


def test_position_is_held_exactly_on_weekday_bars() -> None:
    # Two full weeks. Through the engine the target decided at bar i fills at
    # bar i+1's open, so the position live during bar b reflects bar b's own
    # weekday: long on Mon-Fri, flat on Sat-Sun.
    series = _daily_series(15)
    result = run_backtest(
        DogeWeeklySeasonality(),
        series,
        MarketSpec("DOGE-USDT", "spot"),
        10_000.0,
        costs=CostModel(fee_bps=0.0, slippage_bps=0.0),
        sizing=Sizing.ON_ENTRY,
    )
    held = np.zeros(len(series), dtype=bool)
    for entry_ts, exit_ts in position_spans(result.fills):
        entry = int(np.searchsorted(series.ts, entry_ts))
        end = len(series) if exit_ts is None else int(np.searchsorted(series.ts, exit_ts))
        held[entry:end] = True

    weekday = np.array(
        [dt.datetime.fromtimestamp(int(ts) / 1000, dt.UTC).weekday() for ts in series.ts]
    )
    is_weekday = weekday < 5
    # Bar 0 cannot be entered (no prior decision fills it); ignore it.
    assert list(held[1:]) == list(is_weekday[1:])


def test_signal_does_not_depend_on_price() -> None:
    flat = _daily_series(7)
    crashing = _daily_series(7, closes=[100.0, 50.0, 25.0, 12.0, 6.0, 3.0, 1.0])

    assert _targets(DogeWeeklySeasonality(), flat) == _targets(
        DogeWeeklySeasonality(), crashing
    )


def test_signal_is_prefix_invariant_to_future_bars() -> None:
    short = _daily_series(5)
    long = _daily_series(30)
    short_ctx = Context(short)
    long_ctx = Context(long)

    for index in range(len(short)):
        short_ctx.seek(index)
        long_ctx.seek(index)
        assert DogeWeeklySeasonality().on_bar(short_ctx) == (
            DogeWeeklySeasonality().on_bar(long_ctx)
        )


def test_weekend_only_and_buy_and_hold_extremes() -> None:
    series = _daily_series(7)
    weekend = DogeWeeklySeasonality(WeeklySeasonalityParams(held_days=(5, 6)))
    always = DogeWeeklySeasonality(
        WeeklySeasonalityParams(held_days=(0, 1, 2, 3, 4, 5, 6))
    )

    # Decided weekdays over bars 0..6 are Tue,Wed,Thu,Fri,Sat,Sun,Mon.
    assert _targets(weekend, series) == [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0]
    assert _targets(always, series) == [1.0] * 7


def test_size_scales_the_target() -> None:
    series = _daily_series(2)
    strategy = DogeWeeklySeasonality(
        WeeklySeasonalityParams(held_days=(0, 1, 2, 3, 4), size=0.25)
    )
    # Bar 0 (Monday) decides for Tuesday, a held weekday.
    ctx = Context(series)
    ctx.seek(0)
    assert strategy.on_bar(ctx).target == pytest.approx(0.25)


def test_reset_is_a_noop_and_snapshot_is_stable() -> None:
    strategy = DogeWeeklySeasonality()
    before = strategy.snapshot_state()
    strategy.reset()
    assert strategy.snapshot_state() == before


@pytest.mark.parametrize(
    "held_days",
    [
        (),
        (7,),
        (-1, 0),
        (0, 0, 1),
        (1, 0),
    ],
)
def test_invalid_held_days_are_rejected(held_days: tuple[int, ...]) -> None:
    with pytest.raises(ValueError):
        WeeklySeasonalityParams(held_days=held_days)


@pytest.mark.parametrize("size", [0.0, -0.1, 1.5])
def test_invalid_size_is_rejected(size: float) -> None:
    with pytest.raises(ValueError):
        WeeklySeasonalityParams(size=size)
