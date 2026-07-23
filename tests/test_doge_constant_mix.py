"""Tests for the deployed DOGE constant-mix allocation policy."""

from __future__ import annotations

import numpy as np
import pytest

from cq.context import Context, Series
from cq.core.types import CostModel, Intent, MarketSpec, Sizing
from cq.engine.loop import run_backtest
from cq.engine.sim import SimBroker
from cq.strategy.doge_constant_mix import DogeConstantMix, DogeConstantMixConfig

DAY_MS = 24 * 60 * 60 * 1000
SPEC = MarketSpec("DOGE-USDT", "spot")


def _oscillating_series(
    bars: int = 400,
    amplitude: float = 0.4,
    seed: int = 5,
) -> Series:
    rng = np.random.default_rng(seed)
    phase = np.sin(np.linspace(0.0, 12.0 * np.pi, bars))
    close = np.clip(
        1.0 + amplitude * phase + 0.02 * rng.normal(size=bars),
        0.2,
        None,
    )
    open_ = np.r_[close[0], close[:-1]]
    return Series(
        "DOGE-USDT",
        "1d",
        np.arange(bars, dtype=np.int64) * DAY_MS,
        open_,
        np.maximum(open_, close) * 1.01,
        np.minimum(open_, close) * 0.99,
        close,
        np.ones(bars, dtype=float),
    )


def _targets(strategy: DogeConstantMix, series: Series) -> np.ndarray:
    context = Context(series)
    targets = np.zeros(len(series), dtype=float)
    for index in range(len(series)):
        context.seek(index)
        targets[index] = strategy.on_bar(context).target
    return targets


def _fills(sizing: Sizing, dust: float | None, series: Series) -> int:
    strategy = DogeConstantMix()
    result = run_backtest(
        strategy,
        series,
        SPEC,
        10_000.0,
        costs=CostModel(fee_bps=10.0, slippage_bps=5.0),
        sizing=sizing,
        dust_fraction=dust,
    )
    return len(result.fills)


def test_target_is_constant_and_reads_no_history() -> None:
    strategy = DogeConstantMix(DogeConstantMixConfig(weight=0.3, band=0.1))
    first = _targets(strategy, _oscillating_series(seed=1))
    second = _targets(strategy, _oscillating_series(seed=99, amplitude=0.7))

    assert strategy.warmup_bars == 1
    assert np.all(first == 0.3)
    assert np.all(second == 0.3)


def test_static_allocation_trades_once_then_drifts() -> None:
    assert _fills(Sizing.ON_ENTRY, None, _oscillating_series()) == 1


def test_wider_band_rebalances_less_often() -> None:
    series = _oscillating_series()
    continuous = _fills(Sizing.REBALANCE, None, series)
    narrow = _fills(Sizing.REBALANCE, 0.05, series)
    wide = _fills(Sizing.REBALANCE, 0.20, series)

    assert continuous >= narrow >= wide >= 1
    assert wide < continuous


def test_default_dust_fraction_matches_the_explicit_broker_default() -> None:
    series = _oscillating_series(seed=7)
    strategy = DogeConstantMix()
    default = run_backtest(
        strategy,
        series,
        SPEC,
        10_000.0,
        sizing=Sizing.REBALANCE,
        dust_fraction=None,
    )
    explicit = run_backtest(
        DogeConstantMix(),
        series,
        SPEC,
        10_000.0,
        sizing=Sizing.REBALANCE,
        dust_fraction=SimBroker.DEFAULT_DUST_FRACTION,
    )

    assert default.equity == explicit.equity
    assert [fill.ts for fill in default.fills] == [fill.ts for fill in explicit.fills]


def test_default_configuration_and_name() -> None:
    strategy = DogeConstantMix()

    assert strategy.weight == 0.3
    assert strategy.band == 0.1
    assert strategy.name == "doge-cmix-w0.3-b0.1"


@pytest.mark.parametrize(
    ("weight", "band"),
    [(-0.1, 0.1), (0.0, 0.1), (1.5, 0.1), (0.3, 0.0), (0.3, 1.0)],
)
def test_invalid_configuration_is_rejected(weight: float, band: float) -> None:
    with pytest.raises(ValueError, match=r"weight|band"):
        DogeConstantMixConfig(weight=weight, band=band)


def test_checkpoint_round_trip_and_configuration_guard() -> None:
    strategy = DogeConstantMix(DogeConstantMixConfig(weight=0.4, band=0.2))
    strategy.restore_state(strategy.snapshot_state())

    with pytest.raises(ValueError, match="configuration does not match"):
        strategy.restore_state(DogeConstantMix().snapshot_state())


def test_strategy_emits_its_named_target() -> None:
    series = _oscillating_series()
    context = Context(series)
    context.seek(len(series) - 1)
    strategy = DogeConstantMix()

    assert strategy.on_bar(context) == Intent(
        target=0.3,
        reason="doge-cmix-w0.3-b0.1",
    )
