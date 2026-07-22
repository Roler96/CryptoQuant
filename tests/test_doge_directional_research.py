from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

import numpy as np
import pytest

from cq.context import Context, Series
from cq.core.types import Intent
from cq.research.split import to_ms
from cq.strategy.doge_dvr import DogeDvrTail20
from research.explore_doge_directional_regimes import (
    DogeDirectionalEfficiencyBreakout,
    DogeDirectionalVariance,
    DogeMomentumPersistenceEnsemble,
)
from research.explore_doge_dvr_tail_risk import DogeDvrTailRisk, DvrTailParams
from research.explore_doge_event_geometry import (
    DacParams,
    DogeDiffuseAccumulation,
    DogePositiveJumpCascade,
    PjsParams,
)
from research.validate_doge_dvr_tail20_2026 import _matched_random_null

HOUR_MS = 60 * 60 * 1000


class _StatefulStrategy(Protocol):
    @property
    def warmup_bars(self) -> int: ...

    def reset(self) -> None: ...

    def on_bar(self, ctx: Context) -> Intent: ...

    def snapshot_state(self) -> dict[str, object]: ...


StrategyFactory = Callable[[], _StatefulStrategy]

STRATEGY_FACTORIES: tuple[StrategyFactory, ...] = (
    DogeDirectionalVariance,
    DogeMomentumPersistenceEnsemble,
    DogeDirectionalEfficiencyBreakout,
    DogeDvrTailRisk,
    DogeDiffuseAccumulation,
    DogePositiveJumpCascade,
    DogeDvrTail20,
)


def _random_series(seed: int = 17, bars: int = 2_400) -> Series:
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0002, 0.025, bars)
    close = 100.0 * np.exp(np.cumsum(returns))
    open_ = np.r_[close[0], close[:-1]]
    spread = rng.uniform(0.001, 0.02, bars)
    high = np.maximum(open_, close) * (1.0 + spread)
    low = np.minimum(open_, close) * (1.0 - spread)
    return Series(
        "DOGE-USDT",
        "1h",
        np.arange(bars, dtype=np.int64) * HOUR_MS,
        open_,
        high,
        low,
        close,
        rng.lognormal(14.0, 0.8, bars),
    )


def _close_series(close: list[float]) -> Series:
    values = np.asarray(close, dtype=float)
    open_ = np.r_[values[0], values[:-1]]
    return Series(
        "DOGE-USDT",
        "1h",
        np.arange(len(values), dtype=np.int64) * HOUR_MS,
        open_,
        np.maximum(open_, values) * 1.01,
        np.minimum(open_, values) * 0.99,
        values,
        np.ones(len(values), dtype=float),
    )


def _targets(factory: StrategyFactory, series: Series) -> np.ndarray:
    strategy = factory()
    context = Context(series)
    targets = np.zeros(len(series), dtype=float)
    for index in range(strategy.warmup_bars - 1, len(series)):
        context.seek(index)
        targets[index] = strategy.on_bar(context).target
    return targets


def _changed_future(series: Series, cutoff: int) -> Series:
    columns = {
        name: np.array(getattr(series, name))
        for name in ("open", "high", "low", "close", "volume")
    }
    scale = np.linspace(3.0, 7.0, len(series) - cutoff - 1)
    for name in ("open", "high", "low", "close"):
        columns[name][cutoff + 1 :] *= scale
    columns["volume"][cutoff + 1 :] *= 100.0
    return Series(
        series.inst_id,
        series.timeframe,
        series.ts,
        columns["open"],
        columns["high"],
        columns["low"],
        columns["close"],
        columns["volume"],
    )


@pytest.mark.parametrize("factory", STRATEGY_FACTORIES)
def test_new_strategy_targets_are_prefix_invariant(factory: StrategyFactory) -> None:
    original = _random_series()
    cutoff = 2_300
    changed = _changed_future(original, cutoff)

    np.testing.assert_array_equal(
        _targets(factory, original)[: cutoff + 1],
        _targets(factory, changed)[: cutoff + 1],
    )


@pytest.mark.parametrize("factory", STRATEGY_FACTORIES)
def test_new_strategy_targets_are_finite_and_long_only(factory: StrategyFactory) -> None:
    targets = _targets(factory, _random_series(seed=23))

    assert np.all(np.isfinite(targets))
    assert np.all(targets >= 0.0)
    assert np.all(targets <= 1.0)


@pytest.mark.parametrize(
    ("factory", "dirty_state"),
    [
        (DogeDirectionalVariance, {"_target": 1.0}),
        (DogeMomentumPersistenceEnsemble, {"_target": 1.0}),
        (DogeDirectionalEfficiencyBreakout, {"_target": 1.0}),
        (
            DogeDvrTailRisk,
            {"_target": 0.25, "_peak_close": 200.0, "_armed": False},
        ),
        (
            DogeDiffuseAccumulation,
            {"_target": 1.0, "_signal_index": 50, "_cooldown_until": 90},
        ),
        (
            DogePositiveJumpCascade,
            {
                "_target": 1.0,
                "_first_jump_index": 40,
                "_signal_index": 50,
                "_cooldown_until": 90,
            },
        ),
        (
            DogeDvrTail20,
            {"_target": 0.25, "_peak_close": 200.0, "_armed": False},
        ),
    ],
)
def test_new_strategy_reset_restores_clean_state(
    factory: StrategyFactory, dirty_state: dict[str, object]
) -> None:
    strategy = factory()
    clean = strategy.snapshot_state()
    for name, value in dirty_state.items():
        setattr(strategy, name, value)
    assert strategy.snapshot_state() != clean

    strategy.reset()

    assert strategy.snapshot_state() == clean


def test_dvr_trailing_exit_disarms_until_original_exit_then_rearms() -> None:
    series = _close_series([100.0, 110.0, 120.0, 130.0, 200.0, 150.0, 180.0, 90.0, 300.0])
    strategy = DogeDvrTailRisk(
        DvrTailParams(
            horizon=3,
            entry_share=0.60,
            exit_share=0.45,
            size=0.25,
            trail_drawdown=0.25,
        )
    )
    context = Context(series)

    context.seek(3)
    assert strategy.on_bar(context).target == pytest.approx(0.25)
    context.seek(4)
    assert strategy.on_bar(context).target == pytest.approx(0.25)
    assert strategy.snapshot_state()["peak_close"] == pytest.approx(200.0)

    context.seek(5)
    assert strategy.on_bar(context).target == 0.0
    assert strategy.snapshot_state()["armed"] is False

    context.seek(6)
    assert strategy.on_bar(context).target == 0.0
    assert strategy.snapshot_state()["armed"] is False

    context.seek(7)
    assert strategy.on_bar(context).target == 0.0
    assert strategy.snapshot_state()["armed"] is True

    context.seek(8)
    assert strategy.on_bar(context).target == pytest.approx(0.25)
    assert strategy.snapshot_state()["peak_close"] == pytest.approx(300.0)


def test_frozen_dvr_matches_selected_discovery_neighbor() -> None:
    series = _random_series(seed=31)

    np.testing.assert_array_equal(
        _targets(DogeDvrTail20, series),
        _targets(
            lambda: DogeDvrTailRisk(DvrTailParams(trail_drawdown=0.20)),
            series,
        ),
    )


def test_frozen_dvr_checkpoint_round_trip() -> None:
    strategy = DogeDvrTail20()
    strategy._target = 0.25
    strategy._peak_close = 123.0
    strategy._armed = False
    state = strategy.snapshot_state()
    restored = DogeDvrTail20()

    restored.restore_state(state)

    assert restored.snapshot_state() == state


def test_holdout_null_marks_open_episode_to_close_without_exit_cost() -> None:
    bars = 5
    start = to_ms("2026-01-01")
    values = np.full(bars, 100.0)
    series = Series(
        "DOGE-USDT",
        "1d",
        start + np.arange(bars, dtype=np.int64) * 24 * HOUR_MS,
        values,
        values,
        values,
        values,
        np.ones(bars),
    )
    result = _matched_random_null(
        series,
        [(int(series.ts[0]), None)],
        observed=0.0,
        last_evaluation_index=bars - 1,
        samples=10,
        seed=1,
    )
    entry_cost = (1.0 + 5 / 10_000) * (1.0 + 10 / 10_000)

    assert result["null_median"] == pytest.approx(0.25 * (1.0 - entry_cost))


@pytest.mark.parametrize(
    "factory",
    [
        lambda: DogeDiffuseAccumulation(
            DacParams(
                momentum_hours=2,
                history_hours=4,
                momentum_quantile=0.50,
                min_effective_bars=None,
                hold_hours=3,
                cooldown_hours=2,
                size=0.40,
            )
        ),
        lambda: DogePositiveJumpCascade(
            PjsParams(
                history_hours=4,
                jump_quantile=0.50,
                cluster_hours=3,
                confirmations=1,
                hold_hours=3,
                cooldown_hours=2,
                size=0.40,
            )
        ),
    ],
    ids=("diffuse-accumulation", "positive-jump-cascade"),
)
def test_event_strategy_enforces_fixed_hold_and_cooldown(factory: StrategyFactory) -> None:
    close = np.exp(np.square(np.arange(20, dtype=float)) / 100.0)
    series = _close_series(close.tolist())
    strategy = factory()
    context = Context(series)
    entry_index = strategy.warmup_bars - 1

    context.seek(entry_index)
    assert strategy.on_bar(context).target == pytest.approx(0.40)

    for index in range(entry_index + 1, entry_index + 3):
        context.seek(index)
        assert strategy.on_bar(context).target == pytest.approx(0.40)

    exit_index = entry_index + 3
    context.seek(exit_index)
    assert strategy.on_bar(context).target == 0.0
    assert strategy.snapshot_state()["cooldown_until"] == exit_index + 2

    context.seek(exit_index + 1)
    assert strategy.on_bar(context).target == 0.0

    context.seek(exit_index + 2)
    assert strategy.on_bar(context).target == pytest.approx(0.40)
