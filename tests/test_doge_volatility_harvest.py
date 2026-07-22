"""Tests for the DOGE constant-mix volatility-harvest study.

Two things need pinning: that the constant-mix strategy forecasts nothing (its
target never depends on the bars it sees), and that the engine's `dust_fraction`
is exactly the rebalance band the study relies on — a wider band trades less,
and a static allocation of the same weight trades once and then drifts.
"""

from __future__ import annotations

import numpy as np
import pytest

from cq.context import Context, Series
from cq.core.types import CostModel, MarketSpec, Sizing
from cq.engine.loop import run_backtest
from cq.engine.sim import SimBroker
from research.explore_doge_volatility_harvest import DogeConstantMix, _run, _summary

HOUR_MS = 60 * 60 * 1000
SPEC = MarketSpec("DOGE-USDT", "spot")


def _oscillating_series(bars: int = 400, amplitude: float = 0.4, seed: int = 5) -> Series:
    """A price that swings enough to cross any sane rebalance band repeatedly."""
    rng = np.random.default_rng(seed)
    phase = np.sin(np.linspace(0.0, 12.0 * np.pi, bars))
    close = np.clip(1.0 + amplitude * phase + 0.02 * rng.normal(size=bars), 0.2, None)
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * 1.01
    low = np.minimum(open_, close) * 0.99
    return Series(
        "DOGE-USDT",
        "1d",
        np.arange(bars, dtype=np.int64) * 24 * HOUR_MS,
        open_,
        high,
        low,
        close,
        np.ones(bars, dtype=float),
    )


def _targets(strategy: DogeConstantMix, series: Series) -> np.ndarray:
    context = Context(series)
    out = np.zeros(len(series), dtype=float)
    for index in range(strategy.warmup_bars - 1, len(series)):
        context.seek(index)
        out[index] = strategy.on_bar(context).target
    return out


def test_constant_mix_target_is_the_weight_and_reads_no_history() -> None:
    strategy = DogeConstantMix(0.3)
    a = _targets(strategy, _oscillating_series(seed=1))
    b = _targets(strategy, _oscillating_series(seed=99, amplitude=0.7))
    assert strategy.warmup_bars == 1
    assert np.all(a == 0.3)
    # A different price path cannot change a forecast that does not exist.
    assert np.all(b == 0.3)


@pytest.mark.parametrize("weight", [-0.1, 0.0, 1.5])
def test_constant_mix_rejects_out_of_range_weight(weight: float) -> None:
    with pytest.raises(ValueError, match="weight"):
        DogeConstantMix(weight)


def test_constant_mix_checkpoint_round_trip() -> None:
    strategy = DogeConstantMix(0.4)
    strategy.restore_state(strategy.snapshot_state())
    with pytest.raises(ValueError, match="weight"):
        strategy.restore_state({"weight": 0.25})


def _fills(sizing: Sizing, dust: float | None, series: Series, weight: float = 0.3) -> int:
    result = run_backtest(
        DogeConstantMix(weight),
        series,
        SPEC,
        10_000.0,
        costs=CostModel(fee_bps=10.0, slippage_bps=5.0),
        sizing=sizing,
        dust_fraction=dust,
    )
    return len(result.fills)


def test_static_allocation_trades_once_then_drifts() -> None:
    # ON_ENTRY with an unchanged target sizes once and never rebalances.
    assert _fills(Sizing.ON_ENTRY, None, _oscillating_series()) == 1


def test_wider_band_rebalances_less_often() -> None:
    series = _oscillating_series()
    continuous = _fills(Sizing.REBALANCE, None, series)
    narrow = _fills(Sizing.REBALANCE, 0.05, series)
    wide = _fills(Sizing.REBALANCE, 0.20, series)
    # The band is a no-trade threshold: widening it can only remove trades.
    assert continuous >= narrow >= wide
    # And it genuinely gates: a wide band trades far less than continuous.
    assert wide < continuous
    # A band rebalancer still trades more than a static allocation that never does.
    assert wide >= 1


def test_dust_fraction_none_matches_the_broker_default() -> None:
    series = _oscillating_series(seed=7)
    default = run_backtest(
        DogeConstantMix(0.3), series, SPEC, 10_000.0, sizing=Sizing.REBALANCE,
        dust_fraction=None,
    )
    explicit = run_backtest(
        DogeConstantMix(0.3), series, SPEC, 10_000.0, sizing=Sizing.REBALANCE,
        dust_fraction=SimBroker.DEFAULT_DUST_FRACTION,
    )
    assert default.equity == explicit.equity
    assert [f.ts for f in default.fills] == [f.ts for f in explicit.fills]


def test_band_rebalance_caps_drawdown_below_static_on_a_pump() -> None:
    # A pump-then-crash path: static weight balloons and eats the full crash;
    # the band rebalancer trims into the pump and its drawdown stays bounded.
    up = np.linspace(1.0, 50.0, 200)
    down = np.linspace(50.0, 3.0, 200)
    close = np.r_[up, down]
    open_ = np.r_[close[0], close[:-1]]
    series = Series(
        "DOGE-USDT", "1d",
        np.arange(len(close), dtype=np.int64) * 24 * HOUR_MS,
        open_, np.maximum(open_, close) * 1.001, np.minimum(open_, close) * 0.999,
        close, np.ones(len(close), dtype=float),
    )
    static = _summary(_run(0.3, Sizing.ON_ENTRY, None, series))
    band = _summary(_run(0.3, Sizing.REBALANCE, 0.1, series))
    assert band["max_drawdown"] < static["max_drawdown"]
    # The static sleeve balloons, so its drawdown approaches a full-weight crash.
    assert static["max_drawdown"] > 0.8
