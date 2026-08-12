"""Causality and timing tests for volume-clock continuation research."""

from __future__ import annotations

import numpy as np
import pytest

from cq.context import Context, Series
from cq.research.volume_clock import (
    BARS_PER_DAY,
    FIVE_MINUTES_MS,
    VolumeClockConfig,
    VolumeClockStrategy,
    volume_clock_target,
)


def _target_inputs(
    config: VolumeClockConfig,
    *,
    jump: bool = False,
    capacity_ratio: float = 2.0,
) -> dict[str, np.ndarray]:
    count = 2 * config.max_span + 1
    returns = np.zeros(count - 1)
    returns[-6:] = 0.01
    if jump:
        returns[-6:] = np.array([0.001, 0.001, 0.028, 0.001, 0.001, 0.028])
    closes = 100.0 * np.exp(np.r_[0.0, np.cumsum(returns)])
    opens = np.r_[closes[0], closes[:-1]]
    highs = np.maximum(opens, closes) * 1.001
    lows = np.minimum(opens, closes) / 1.001
    volumes = 100.0 / closes
    timestamps = np.arange(count, dtype=np.int64) * FIVE_MINUTES_MS
    current_slot = int(timestamps[-1] // FIVE_MINUTES_MS) % BARS_PER_DAY
    entry_slot = (current_slot + 1) % BARS_PER_DAY
    seasonal = np.full(BARS_PER_DAY, 100.0)
    for offset in range(config.hold_bars):
        seasonal[(entry_slot + offset) % BARS_PER_DAY] = 100.0 * capacity_ratio
    return {
        "timestamps": timestamps,
        "opens": opens,
        "highs": highs,
        "lows": lows,
        "closes": closes,
        "volumes": volumes,
        "seasonal_dvol": seasonal,
    }


def _strategy_series(config: VolumeClockConfig, *, future_open_shift: float = 0.0) -> Series:
    days = config.seasonal_days + 1
    count = days * BARS_PER_DAY + config.hold_bars + 8
    timestamps = np.arange(count, dtype=np.int64) * FIVE_MINUTES_MS
    returns = np.zeros(count - 1)
    decision = days * BARS_PER_DAY + 6
    returns[decision - 5 : decision + 1] = 0.01
    closes = 100.0 * np.exp(np.r_[0.0, np.cumsum(returns)])
    opens = np.r_[closes[0], closes[:-1]]
    if future_open_shift:
        opens[decision + 1] += future_open_shift
    highs = np.maximum(opens, closes) * 1.001
    lows = np.minimum(opens, closes) / 1.001
    seasonal = np.full(BARS_PER_DAY, 100.0)
    current_slot = decision % BARS_PER_DAY
    entry_slot = (current_slot + 1) % BARS_PER_DAY
    for offset in range(config.hold_bars):
        seasonal[(entry_slot + offset) % BARS_PER_DAY] = 200.0
    volumes = np.empty(count)
    for index in range(count):
        volumes[index] = seasonal[index % BARS_PER_DAY] / closes[index]
    return Series(
        "DOGE-USDT-SWAP",
        "5m",
        timestamps,
        opens,
        highs,
        lows,
        closes,
        volumes,
    )


def test_target_follows_two_coherent_volume_buckets() -> None:
    config = VolumeClockConfig(
        seasonal_days=2,
        bucket_size=3.0,
        coherence_threshold=0.80,
        capacity_ratio=1.50,
        hold_bars=6,
        max_span=12,
    )

    assert volume_clock_target(config=config, **_target_inputs(config)) == 1.0


def test_target_rejects_a_single_jump_and_missing_capacity_expansion() -> None:
    config = VolumeClockConfig(
        seasonal_days=2,
        bucket_size=3.0,
        coherence_threshold=0.60,
        capacity_ratio=1.50,
        hold_bars=6,
        max_span=12,
    )

    assert volume_clock_target(config=config, **_target_inputs(config, jump=True)) == 0.0
    assert (
        volume_clock_target(
            config=config,
            **_target_inputs(config, capacity_ratio=1.0),
        )
        == 0.0
    )


def test_target_rejects_a_discontinuous_or_zero_volume_bucket() -> None:
    config = VolumeClockConfig(
        seasonal_days=2,
        bucket_size=3.0,
        hold_bars=6,
        max_span=12,
    )
    discontinuous = _target_inputs(config)
    discontinuous["timestamps"] = discontinuous["timestamps"].copy()
    discontinuous["timestamps"][-1] += FIVE_MINUTES_MS
    zero_volume = _target_inputs(config)
    zero_volume["volumes"] = zero_volume["volumes"].copy()
    zero_volume["volumes"][-2] = 0.0

    assert volume_clock_target(config=config, **discontinuous) == 0.0
    assert volume_clock_target(config=config, **zero_volume) == 0.0


def test_strategy_decision_is_invariant_to_the_next_open() -> None:
    config = VolumeClockConfig(
        seasonal_days=2,
        bucket_size=3.0,
        coherence_threshold=0.80,
        capacity_ratio=1.50,
        hold_bars=6,
        max_span=12,
    )
    decision = (config.seasonal_days + 1) * BARS_PER_DAY + 6
    targets = []
    for shift in (0.0, 99.0):
        context = Context(_strategy_series(config, future_open_shift=shift))
        context.seek(decision)
        targets.append(VolumeClockStrategy(config).on_bar(context).target)

    assert targets == [0.25, 0.25]


def test_strategy_exits_after_the_frozen_hold() -> None:
    config = VolumeClockConfig(
        seasonal_days=2,
        bucket_size=3.0,
        coherence_threshold=0.80,
        capacity_ratio=1.50,
        hold_bars=6,
        max_span=12,
    )
    series = _strategy_series(config)
    decision = (config.seasonal_days + 1) * BARS_PER_DAY + 6
    strategy = VolumeClockStrategy(config)
    context = Context(series)
    targets = []
    for index in range(decision, decision + 7):
        context.seek(index)
        targets.append(strategy.on_bar(context).target)

    assert targets == [0.25, 0.25, 0.25, 0.25, 0.25, 0.25, 0.0]


def test_config_rejects_invalid_values() -> None:
    constructors = (
        lambda: VolumeClockConfig(seasonal_days=0),
        lambda: VolumeClockConfig(bucket_size=0.0),
        lambda: VolumeClockConfig(coherence_threshold=0.0),
        lambda: VolumeClockConfig(capacity_ratio=0.0),
        lambda: VolumeClockConfig(hold_bars=0),
        lambda: VolumeClockConfig(max_span=0),
        lambda: VolumeClockConfig(jump_share_max=1.1),
        lambda: VolumeClockConfig(target_weight=0.0),
        lambda: VolumeClockConfig(evaluation_start_ms=1, evaluation_end_ms=1),
    )
    for constructor in constructors:
        with pytest.raises(ValueError):
            constructor()
