"""Causality and timing tests for downside-shock recovery research."""

from __future__ import annotations

import numpy as np
import pytest

from cq.context import Context, Series
from cq.research.downside_recovery import (
    DownsideRecoveryConfig,
    DownsideRecoveryStrategy,
    signal_target,
)

BAR_MS = 300_000


def _signal_path(config: DownsideRecoveryConfig) -> np.ndarray:
    baseline_count = config.volatility_window - config.shock_window
    baseline = np.resize(np.array([-0.001, 0.001]), baseline_count)
    returns = np.r_[baseline, np.full(config.shock_window, -0.01), 0.012]
    return 100.0 * np.exp(np.r_[0.0, np.cumsum(returns)])


def _series(closes: np.ndarray, future_open_shift: float = 0.0) -> Series:
    opens = closes.copy()
    if future_open_shift:
        opens[-1] += future_open_shift
    return Series(
        "DOGE-USDT-SWAP",
        "5m",
        np.arange(len(closes), dtype=np.int64) * BAR_MS,
        opens,
        np.maximum(opens, closes),
        np.minimum(opens, closes),
        closes,
        np.full(len(closes), 1_000.0),
    )


def test_signal_detects_partial_recovery_after_downside_shock() -> None:
    config = DownsideRecoveryConfig()
    closes = _signal_path(config)

    assert signal_target(closes, np.ones(len(closes)), config) == 1.0


def test_signal_rejects_zero_volume_in_shock_path() -> None:
    config = DownsideRecoveryConfig()
    closes = _signal_path(config)
    volumes = np.ones(len(closes))
    volumes[-3] = 0.0

    assert signal_target(closes, volumes, config) == 0.0


def test_signal_rejects_an_oversized_recovery() -> None:
    config = DownsideRecoveryConfig()
    closes = _signal_path(config)
    closes[-1] = closes[-2] * np.exp(0.04)

    assert signal_target(closes, np.ones(len(closes)), config) == 0.0


def test_decision_is_invariant_to_future_open() -> None:
    config = DownsideRecoveryConfig()
    closes = _signal_path(config)
    targets = []
    for shift in (0.0, 99.0):
        series = _series(closes, future_open_shift=shift)
        context = Context(series)
        context.seek(len(series) - 1)
        targets.append(DownsideRecoveryStrategy(config).on_bar(context).target)

    assert targets == [0.25, 0.25]


def test_fixed_hold_exits_after_twelve_complete_bars() -> None:
    config = DownsideRecoveryConfig(hold_bars=12)
    path = _signal_path(config)
    closes = np.r_[path, np.repeat(path[-1], 13)]
    strategy = DownsideRecoveryStrategy(config)
    context = Context(_series(closes))
    targets = []
    first = len(path) - 1
    for index in range(first, first + 13):
        context.seek(index)
        targets.append(strategy.on_bar(context).target)

    assert targets[0] == 0.25
    assert targets[1:12] == [0.25] * 11
    assert targets[12] == 0.0


def test_config_rejects_invalid_values() -> None:
    constructors = (
        lambda: DownsideRecoveryConfig(shock_window=1),
        lambda: DownsideRecoveryConfig(volatility_window=3),
        lambda: DownsideRecoveryConfig(shock_z=0.0),
        lambda: DownsideRecoveryConfig(recovery_floor=0.9, recovery_ceiling=0.8),
        lambda: DownsideRecoveryConfig(hold_bars=0),
        lambda: DownsideRecoveryConfig(target_weight=1.1),
    )
    for constructor in constructors:
        with pytest.raises(ValueError):
            constructor()


def test_checkpoint_restores_hold_state_and_rebuilds_statistics() -> None:
    config = DownsideRecoveryConfig(hold_bars=12)
    path = _signal_path(config)
    strategy = DownsideRecoveryStrategy(config)
    context = Context(_series(path))
    context.seek(len(path) - 1)
    assert strategy.on_bar(context).target == 0.25

    state = strategy.snapshot_state()
    restored = DownsideRecoveryStrategy(config)
    restored.restore_state(state)

    assert restored.snapshot_state() == state
    assert restored._last_index is None


def test_checkpoint_rejects_a_different_frozen_config() -> None:
    state = DownsideRecoveryStrategy().snapshot_state()

    with pytest.raises(ValueError, match="configuration does not match"):
        DownsideRecoveryStrategy(DownsideRecoveryConfig(shock_z=6.0)).restore_state(state)
