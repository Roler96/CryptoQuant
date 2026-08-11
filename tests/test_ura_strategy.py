"""URA v1 signal timing and causal-state tests."""

from __future__ import annotations

from itertools import pairwise

import numpy as np

from cq.context import Context, Series
from cq.core.types import CostModel, MarketSpec, Sizing
from cq.engine.loop import run_backtest
from cq.research.ura.signals import (
    UraConfig,
    UraStrategy,
    build_schedule,
    condition_funnel,
)

HOUR = 3_600_000


def _series(closes: list[float], *, future_open_shift: float = 0.0) -> Series:
    values = np.asarray(closes, dtype=float)
    opens = values.copy()
    if future_open_shift:
        opens[25:] += future_open_shift
    return Series(
        "DOGE-USDT",
        "1h",
        np.arange(len(values), dtype=np.int64) * HOUR,
        opens,
        np.maximum(opens, values),
        np.minimum(opens, values),
        values,
        np.full(len(values), 100.0),
    )


def _acceptance_path(length: int = 80) -> list[float]:
    # Prior 24: upper share=.50, lower share=.25. Current location=.833,
    # below the old high, so decision index 24 is an exact main signal.
    reference = [1.0] * 6 + [2.0] * 6 + [4.0] * 12
    values: list[float] = []
    while len(values) < length:
        values.extend(reference)
        values.append(3.5)
    return values[:length]


def _intent_at(series: Series, index: int):
    ctx = Context(series)
    ctx.seek(index)
    strategy = UraStrategy(UraConfig(evaluation_end_ms=len(series) * HOUR))
    return strategy.on_bar(ctx)


def test_signal_uses_only_prior_window_and_closed_current_bar() -> None:
    first = _series(_acceptance_path(), future_open_shift=0.0)
    second = _series(_acceptance_path(), future_open_shift=99.0)

    assert _intent_at(first, 24).target == 0.25
    assert _intent_at(second, 24).target == 0.25


def test_true_breakout_and_zero_volume_window_are_rejected() -> None:
    closes = _acceptance_path()
    closes[24] = 4.01
    breakout = _series(closes)
    assert _intent_at(breakout, 24).target == 0.0

    zero_volume = _series(_acceptance_path())
    volumes = np.array(zero_volume.volume)
    volumes[0] = 0.0
    zero_volume = Series(
        zero_volume.inst_id,
        zero_volume.timeframe,
        zero_volume.ts,
        zero_volume.open,
        zero_volume.high,
        zero_volume.low,
        zero_volume.close,
        volumes,
    )
    assert _intent_at(zero_volume, 24).target == 0.0


def test_fixed_hold_exits_after_24_complete_bars_and_skips_same_open_reentry() -> None:
    series = _series(_acceptance_path())
    strategy = UraStrategy(UraConfig(evaluation_end_ms=len(series) * HOUR))
    ctx = Context(series)
    targets = []
    for index in range(24, 50):
        ctx.seek(index)
        targets.append(strategy.on_bar(ctx).target)

    assert targets[0] == 0.25  # decision 24 -> entry open 25
    assert targets[1:24] == [0.25] * 23
    assert targets[24] == 0.0  # decision 48 -> exit open 49
    assert targets[25] == 0.25  # decision 49 -> earliest next entry open 50


def test_schedule_matches_strategy_entry_exit_indices_without_overlap() -> None:
    series = _series(_acceptance_path(120))
    events = build_schedule(series, UraConfig(evaluation_end_ms=len(series) * HOUR))

    assert events[0].decision_index == 24
    assert events[0].entry_index == 25
    assert events[0].exit_index == 49
    assert all(right.entry_index > left.exit_index for left, right in pairwise(events))


def test_end_boundary_requires_exit_strictly_before_end() -> None:
    series = _series(_acceptance_path(50))
    events = build_schedule(series, UraConfig(evaluation_end_ms=49 * HOUR))

    assert events == []  # first possible exit time equals end and is excluded


def test_schedule_reconciles_with_shared_engine_fill_timing() -> None:
    series = _series(_acceptance_path(120))
    config = UraConfig(evaluation_end_ms=len(series) * HOUR)
    schedule = build_schedule(series, config)

    result = run_backtest(
        UraStrategy(config),
        series,
        MarketSpec("DOGE-USDT", "spot", lot_size=0.0, min_notional=0.0),
        costs=CostModel(fee_bps=0.0, slippage_bps=0.0),
        sizing=Sizing.ON_ENTRY,
        dust_fraction=0.0,
    )

    expected = [
        timestamp
        for event in schedule
        for timestamp in (int(series.ts[event.entry_index]), int(series.ts[event.exit_index]))
    ]
    assert [fill.ts for fill in result.fills] == expected
    assert result.rejections == []


def test_condition_funnel_is_monotone_and_ends_at_raw_signal_count() -> None:
    series = _series(_acceptance_path(120))
    config = UraConfig(evaluation_end_ms=len(series) * HOUR)
    funnel = condition_funnel(series, config)

    counts = list(funnel.values())
    assert counts == sorted(counts, reverse=True)
    assert funnel["raw_signals"] >= len(build_schedule(series, config))
