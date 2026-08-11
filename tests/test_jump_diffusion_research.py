"""Causality and timing tests for jump-diffusion confirmation research."""

from __future__ import annotations

import numpy as np
import pytest

from cq.context import Context, Series
from cq.research.jump_diffusion import (
    JumpDiffusionConfig,
    JumpDiffusionStrategy,
    confirmed_jump_target,
)

BAR_MS = 300_000


def _confirmed_path(config: JumpDiffusionConfig) -> tuple[np.ndarray, ...]:
    reference = np.resize(np.array([-0.001, 0.001]), config.diffusion_window)
    returns = np.r_[reference, 0.020, np.full(config.confirm_bars, 0.001)]
    closes = 100.0 * np.exp(np.r_[0.0, np.cumsum(returns)])
    opens = closes.copy()
    highs = np.maximum(opens, closes) * 1.001
    lows = np.minimum(opens, closes) / 1.001
    jump_index = config.diffusion_window + 1
    highs[jump_index] = closes[jump_index] * 1.001
    lows[jump_index] = closes[jump_index - 1] / 1.001
    volumes = np.ones(len(closes))
    volumes[jump_index] = 3.0
    return opens, highs, lows, closes, volumes


def _series(arrays: tuple[np.ndarray, ...], future_open_shift: float = 0.0) -> Series:
    opens, highs, lows, closes, volumes = (values.copy() for values in arrays)
    if future_open_shift:
        opens[-1] += future_open_shift
        highs[-1] = max(highs[-1], opens[-1])
        lows[-1] = min(lows[-1], opens[-1])
    return Series(
        "DOGE-USDT-SWAP",
        "5m",
        np.arange(len(closes), dtype=np.int64) * BAR_MS,
        opens,
        highs,
        lows,
        closes,
        volumes,
    )


def test_confirmed_jump_target_follows_a_retained_jump() -> None:
    config = JumpDiffusionConfig(diffusion_window=12, jump_z=4.0, confirm_bars=2)
    _opens, highs, lows, closes, volumes = _confirmed_path(config)

    assert confirmed_jump_target(highs, lows, closes, volumes, config) == 1.0


def test_confirmed_jump_target_rejects_a_reverted_jump() -> None:
    config = JumpDiffusionConfig(diffusion_window=12, jump_z=4.0, confirm_bars=2)
    _opens, highs, lows, closes, volumes = _confirmed_path(config)
    closes[-2:] = closes[config.diffusion_window] * 1.002
    highs[-2:] = np.maximum(highs[-2:], closes[-2:])
    lows[-2:] = np.minimum(lows[-2:], closes[-2:])

    assert confirmed_jump_target(highs, lows, closes, volumes, config) == 0.0


def test_decision_is_invariant_to_next_open() -> None:
    config = JumpDiffusionConfig(diffusion_window=12, jump_z=4.0, confirm_bars=2)
    arrays = _confirmed_path(config)
    targets = []
    for shift in (0.0, 99.0):
        context = Context(_series(arrays, future_open_shift=shift))
        context.seek(len(arrays[3]) - 1)
        targets.append(JumpDiffusionStrategy(config).on_bar(context).target)

    assert targets == [0.25, 0.25]


def test_fixed_hold_exits_after_the_configured_bars() -> None:
    config = JumpDiffusionConfig(
        diffusion_window=12,
        jump_z=4.0,
        confirm_bars=2,
        hold_bars=6,
    )
    arrays = _confirmed_path(config)
    extension = 7
    extended = tuple(
        np.r_[values, np.repeat(values[-1], extension)] for values in arrays
    )
    strategy = JumpDiffusionStrategy(config)
    context = Context(_series(extended))
    first = len(arrays[3]) - 1
    targets = []
    for index in range(first, first + 7):
        context.seek(index)
        targets.append(strategy.on_bar(context).target)

    assert targets[0] == 0.25
    assert targets[1:6] == [0.25] * 5
    assert targets[6] == 0.0


def test_config_rejects_invalid_values() -> None:
    constructors = (
        lambda: JumpDiffusionConfig(diffusion_window=2),
        lambda: JumpDiffusionConfig(jump_z=0.0),
        lambda: JumpDiffusionConfig(body_ratio=1.1),
        lambda: JumpDiffusionConfig(volume_ratio=0.0),
        lambda: JumpDiffusionConfig(confirm_bars=0),
        lambda: JumpDiffusionConfig(retention=1.1),
        lambda: JumpDiffusionConfig(hold_bars=0),
        lambda: JumpDiffusionConfig(target_weight=1.1),
    )
    for constructor in constructors:
        with pytest.raises(ValueError):
            constructor()
