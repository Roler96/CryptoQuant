"""Synthetic-bar tests for the frozen DLSR v1 strategy.

Every series is synthetic and built to exercise one frozen rule at a time.
Timestamp gaps abort the run because the existing engine's pending-order
semantics cannot reproduce the protocol's exact recovery-open behavior without
framework changes.
"""

from __future__ import annotations

import numpy as np
import pytest

from cq.context import Context, Series
from cq.core.types import Intent, MarketSpec, Side, Sizing
from cq.engine.loop import run_backtest
from cq.strategy.doge_dlsr import (
    BAR_MS,
    FAMILY_TRIALS,
    FROZEN_VERSIONS,
    DogeDlsr,
    DogeDlsrConfig,
)

SPEC = MarketSpec("DOGE-USDT", "spot")
T0 = 1_600_000_000_000
BASELINE = 2016
# Flat baseline bar: log-range ~0.001, volume 100, prior-hour floor 0.9995.
FLAT_LOW = 0.9995


def _event(
    loc: float = 0.8,
    depth: float = 0.002,
    log_range: float = 0.006,
    volume: float = 400.0,
    low: float | None = None,
    close: float | None = None,
) -> dict[str, float]:
    """A sweep-reclaim bar relative to the flat baseline's 0.9995 floor."""
    if low is None:
        low = FLAT_LOW * float(np.exp(-depth))
    high = low * float(np.exp(log_range))
    if close is None:
        close = low + loc * (high - low)
    return {"open": close, "high": high, "low": low, "close": close, "volume": volume}


def _series(
    n: int,
    overrides: dict[int, dict[str, float]] | None = None,
    drop: tuple[int, ...] = (),
) -> Series:
    """Flat bars with per-index overrides; `drop` removes rows after overrides,
    so a dropped index produces a genuine timestamp gap."""
    columns = {
        "open": np.full(n, 1.0),
        "high": np.full(n, 1.0005),
        "low": np.full(n, FLAT_LOW),
        "close": np.full(n, 1.0),
        "volume": np.full(n, 100.0),
    }
    for index, fields in (overrides or {}).items():
        for name, value in fields.items():
            columns[name][index] = value
    ts = T0 + np.arange(n, dtype=np.int64) * BAR_MS
    if drop:
        keep = np.ones(n, dtype=bool)
        keep[list(drop)] = False
        ts = ts[keep]
        columns = {name: column[keep] for name, column in columns.items()}
    return Series("DOGE-USDT", "5m", ts, **columns)


def _targets(strategy: DogeDlsr, series: Series) -> np.ndarray:
    context = Context(series)
    targets = np.zeros(len(series), dtype=float)
    for index in range(len(series)):
        context.seek(index)
        targets[index] = strategy.on_bar(context).target
    return targets


E = BASELINE + 4  # signal bar index used by most scenarios


def test_signal_fires_and_holds_twelve_bars() -> None:
    series = _series(E + 40, {E: _event()})
    targets = _targets(DogeDlsr(), series)
    # Pending entry on the signal bar, held through the 12th complete bar
    # after the entry fill, flat from the bar that schedules the exit.
    assert np.all(targets[:E] == 0.0)
    assert np.all(targets[E : E + 12] == 0.25)
    assert np.all(targets[E + 12 :] == 0.0)


@pytest.mark.parametrize(
    "bar",
    [
        pytest.param(_event(low=0.99955), id="low-not-below-floor"),
        pytest.param(_event(depth=0.0002), id="sweep-too-shallow"),
        pytest.param(_event(log_range=0.002), id="range-below-3x-median"),
        pytest.param(_event(volume=250.0), id="volume-below-3x-median"),
        pytest.param(_event(loc=0.5), id="close-location-below-0.75"),
        pytest.param(_event(close=FLAT_LOW * 0.9999), id="close-not-above-floor"),
    ],
)
def test_each_shell_condition_gates(bar: dict[str, float]) -> None:
    series = _series(E + 40, {E: bar})
    targets = _targets(DogeDlsr(), series)
    assert np.all(targets == 0.0)


def test_entry_and_exit_fill_at_planned_opens() -> None:
    series = _series(E + 40, {E: _event()})
    result = run_backtest(DogeDlsr(), series, SPEC, 10_000.0)
    assert [fill.side for fill in result.fills] == [Side.BUY, Side.SELL]
    buy, sell = result.fills
    # Decided on E's close, filled at E+1's open; exit decided on the close of
    # the 12th held bar (E+12), filled at E+13's open. 60 planned minutes.
    assert buy.ts == int(series.ts[E + 1])
    assert sell.ts == int(series.ts[E + 13])
    assert buy.price == pytest.approx(1.0 * 1.0005)
    assert sell.price == pytest.approx(1.0 * 0.9995)
    assert buy.quantity == pytest.approx(0.25 * 10_000.0 / 1.0)


def test_zero_volume_entry_bar_voids_event_without_chasing() -> None:
    # The engine keeps a rejected order pending for the next open; the strategy
    # must overwrite it the moment it sees the untradeable entry bar, so a
    # tradeable E+2 gets no fill at all.
    series = _series(E + 40, {E: _event(), E + 1: {"volume": 0.0}})
    strategy = DogeDlsr()
    result = run_backtest(strategy, series, SPEC, 10_000.0)
    assert result.fills == []
    assert len(result.rejections) == 1
    assert strategy.accepted_events == 1
    assert strategy.voided_entries == 1
    assert strategy.completed_episodes == 0


def test_voided_entry_consumes_event_and_cools_down() -> None:
    second = E + 101  # inside the 144-bar cooldown from the planned entry
    third = E + 1 + 150  # outside it
    series = _series(
        E + 220,
        {
            E: _event(),
            E + 1: {"volume": 0.0},
            second: _event(),
            third: _event(),
        },
    )
    strategy = DogeDlsr()
    result = run_backtest(strategy, series, SPEC, 10_000.0)
    assert strategy.accepted_events == 2  # the in-cooldown shell is ignored
    assert [fill.side for fill in result.fills] == [Side.BUY, Side.SELL]
    assert result.fills[0].ts == int(series.ts[third + 1])


def test_zero_volume_exit_bar_delays_exit() -> None:
    series = _series(E + 40, {E: _event(), E + 13: {"volume": 0.0}})
    strategy = DogeDlsr()
    result = run_backtest(strategy, series, SPEC, 10_000.0)
    assert [fill.side for fill in result.fills] == [Side.BUY, Side.SELL]
    assert result.fills[1].ts == int(series.ts[E + 14])
    assert strategy.completed_episodes == 1


def test_gap_during_hold_aborts_run() -> None:
    # The standard engine would only let the strategy react after the recovery
    # open. Refuse the run instead of reporting a one-bar-late approximation.
    series = _series(E + 40, {E: _event()}, drop=(E + 5,))
    with pytest.raises(ValueError, match="contiguous native 5m"):
        run_backtest(DogeDlsr(), series, SPEC, 10_000.0)


def test_gap_swallowing_entry_bar_aborts_run() -> None:
    # The standard engine would chase the target to the recovery open. The
    # strategy aborts before any result can be returned.
    series = _series(E + 40, {E: _event()}, drop=(E + 1,))
    with pytest.raises(ValueError, match="contiguous native 5m"):
        run_backtest(DogeDlsr(), series, SPEC, 10_000.0)


def test_gap_before_warmup_aborts_run() -> None:
    series = _series(E + 40, {E: _event()}, drop=(100,))
    with pytest.raises(ValueError, match="contiguous native 5m"):
        run_backtest(DogeDlsr(), series, SPEC, 10_000.0)


def test_cooldown_runs_from_exit_fill() -> None:
    exit_fill = E + 13
    blocked = exit_fill + 100
    # Signal at +143 closes exactly at the first eligible entry open (+144).
    allowed_signal = exit_fill + 143
    series = _series(
        E + 220,
        {E: _event(), blocked: _event(), allowed_signal: _event()},
    )
    strategy = DogeDlsr()
    result = run_backtest(strategy, series, SPEC, 10_000.0)
    assert strategy.accepted_events == 2
    assert strategy.completed_episodes == 2
    assert len(result.fills) == 4
    assert result.fills[2].ts == int(series.ts[exit_fill + 144])


def test_illegal_bar_blocks_signal_until_baseline_window_clears() -> None:
    # A bad bar anywhere in the 2016-bar baseline forbids a signal; only after
    # a full clean window re-accumulates may one fire again.
    overrides: dict[int, dict[str, float]] = {E: _event()}
    overrides[E - 100] = {"low": 1.001}
    late = (E - 100) + BASELINE + 10  # window no longer touches the spoiled bar
    overrides[late] = _event()
    series = _series(late + 40, overrides)
    strategy = DogeDlsr()
    targets = _targets(strategy, series)
    assert targets[E] == 0.0
    assert strategy.accepted_events == 1
    assert targets[late] == 0.25


class _TargetRecorder:
    """Wraps the strategy to observe every emitted target through the engine."""

    def __init__(self, inner: DogeDlsr):
        self.inner = inner
        self.targets: list[float] = []

    @property
    def name(self) -> str:
        return self.inner.name

    @property
    def warmup_bars(self) -> int:
        return self.inner.warmup_bars

    def reset(self) -> None:
        self.inner.reset()

    def on_bar(self, ctx: Context) -> Intent:
        intent = self.inner.on_bar(ctx)
        self.targets.append(intent.target)
        return intent


def test_spot_targets_are_only_zero_or_quarter() -> None:
    series = _series(E + 40, {E: _event()})
    recorder = _TargetRecorder(DogeDlsr())
    run_backtest(recorder, series, SPEC, 10_000.0)
    assert set(recorder.targets) == {0.0, 0.25}


def test_snapshot_restore_resumes_identically() -> None:
    series = _series(E + 40, {E: _event()})
    context = Context(series)
    first = DogeDlsr()
    split_at = E + 5  # mid-hold
    for index in range(split_at + 1):
        context.seek(index)
        first.on_bar(context)
    resumed = DogeDlsr()
    resumed.restore_state(first.snapshot_state())
    rest_first: list[float] = []
    rest_resumed: list[float] = []
    for index in range(split_at + 1, len(series)):
        context.seek(index)
        rest_first.append(first.on_bar(context).target)
    context_b = Context(series)
    for index in range(split_at + 1, len(series)):
        context_b.seek(index)
        rest_resumed.append(resumed.on_bar(context_b).target)
    assert rest_first == rest_resumed
    assert first.snapshot_state() == resumed.snapshot_state()


def test_restore_rejects_config_mismatch() -> None:
    snapshot = DogeDlsr().snapshot_state()
    other = DogeDlsr(FROZEN_VERSIONS["hold6"])
    with pytest.raises(ValueError, match="configuration does not match"):
        other.restore_state(snapshot)


def test_non_registered_configuration_is_rejected() -> None:
    with pytest.raises(ValueError, match="seven pre-registered"):
        DogeDlsr(DogeDlsrConfig(range_mult=3.5))


def test_framework_runs_with_frozen_on_entry_sizing() -> None:
    series = _series(E + 40, {E: _event()})
    result = run_backtest(
        DogeDlsr(), series, SPEC, 10_000.0, sizing=Sizing.ON_ENTRY
    )
    assert [fill.side for fill in result.fills] == [Side.BUY, Side.SELL]


def test_two_runs_are_deterministic() -> None:
    series = _series(E + 40, {E: _event()})
    first = run_backtest(DogeDlsr(), series, SPEC, 10_000.0)
    second = run_backtest(DogeDlsr(), series, SPEC, 10_000.0)
    assert first.equity == second.equity
    assert first.fills == second.fills
    assert first.manifest.primary_fingerprint == second.manifest.primary_fingerprint


def test_frozen_family_is_seven_single_axis_versions() -> None:
    assert FAMILY_TRIALS == 7
    expected_axis = {
        "range2": ("range_mult", 2.0),
        "range4": ("range_mult", 4.0),
        "volume2": ("volume_mult", 2.0),
        "volume4": ("volume_mult", 4.0),
        "hold6": ("hold_bars", 6),
        "hold24": ("hold_bars", 24),
    }
    assert set(FROZEN_VERSIONS) == {"main", *expected_axis}
    main = FROZEN_VERSIONS["main"]
    assert main == DogeDlsrConfig()
    for version, (field, value) in expected_axis.items():
        config = FROZEN_VERSIONS[version]
        diffs = {
            name
            for name in vars(main)
            if getattr(config, name) != getattr(main, name)
        }
        assert diffs == {field}
        assert getattr(config, field) == value


def test_non_5m_timeframe_is_rejected() -> None:
    bars = 4
    series = Series(
        "DOGE-USDT",
        "1h",
        T0 + np.arange(bars, dtype=np.int64) * 3_600_000,
        np.full(bars, 1.0),
        np.full(bars, 1.0005),
        np.full(bars, 0.9995),
        np.full(bars, 1.0),
        np.full(bars, 100.0),
    )
    context = Context(series)
    context.seek(0)
    with pytest.raises(ValueError, match="native-5m"):
        DogeDlsr().on_bar(context)


def test_non_doge_instrument_is_rejected() -> None:
    series = _series(4)
    other = Series(
        "BTC-USDT",
        "5m",
        series.ts,
        series.open,
        series.high,
        series.low,
        series.close,
        series.volume,
    )
    context = Context(other)
    context.seek(0)
    with pytest.raises(ValueError, match="frozen for DOGE-USDT"):
        DogeDlsr().on_bar(context)
