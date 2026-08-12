"""Vectorized scan checks for the frozen DOGE VCOS study."""

from __future__ import annotations

import numpy as np
import pandas as pd

from cq.research.volume_clock import FIVE_MINUTES_MS, VolumeClockConfig, volume_clock_target
from scripts.research_doge_vcos import (
    BARS_PER_DAY,
    build_bucket_features,
    build_seasonal_state,
    capacity_expansion,
    vcos_signal,
)


def _frame() -> tuple[pd.DataFrame, int]:
    count = 3 * BARS_PER_DAY
    decision = 2 * BARS_PER_DAY + 50
    returns = np.zeros(count - 1)
    returns[decision - 5 : decision + 1] = 0.01
    closes = 100.0 * np.exp(np.r_[0.0, np.cumsum(returns)])
    opens = np.r_[closes[0], closes[:-1]]
    highs = np.maximum(opens, closes) * 1.001
    lows = np.minimum(opens, closes) / 1.001
    seasonal = np.full(BARS_PER_DAY, 100.0)
    entry_slot = (decision + 1) % BARS_PER_DAY
    for offset in range(6):
        seasonal[(entry_slot + offset) % BARS_PER_DAY] = 200.0
    dvol = seasonal[np.arange(count) % BARS_PER_DAY]
    frame = pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": dvol / closes,
            "quote_volume": dvol,
        },
        index=pd.to_datetime(
            np.arange(count, dtype=np.int64) * FIVE_MINUTES_MS,
            unit="ms",
            utc=True,
        ),
    )
    return frame, decision


def test_vectorized_features_match_the_single_decision_strategy_function() -> None:
    frame, decision = _frame()
    state = build_seasonal_state(frame, 2)
    features = build_bucket_features(frame, state, 3.0)
    capacity = capacity_expansion(state, 6)
    signal = vcos_signal(
        features,
        capacity,
        coherence_threshold=0.80,
        capacity_ratio=1.50,
    )
    config = VolumeClockConfig(
        seasonal_days=2,
        bucket_size=3.0,
        coherence_threshold=0.80,
        capacity_ratio=1.50,
        hold_bars=6,
        max_span=72,
    )

    pure_target = volume_clock_target(
        timestamps=(
            pd.DatetimeIndex(frame.index[: decision + 1]).asi8 // 1_000_000
        ).astype(np.int64),
        opens=frame.open.to_numpy(dtype=float)[: decision + 1],
        highs=frame.high.to_numpy(dtype=float)[: decision + 1],
        lows=frame.low.to_numpy(dtype=float)[: decision + 1],
        closes=frame.close.to_numpy(dtype=float)[: decision + 1],
        volumes=frame.volume.to_numpy(dtype=float)[: decision + 1],
        seasonal_dvol=state.profiles[2],
        config=config,
    )

    assert signal[decision] == pure_target == 1.0


def test_current_day_future_mutations_do_not_change_a_decision() -> None:
    frame, decision = _frame()
    first_state = build_seasonal_state(frame, 2)
    first_features = build_bucket_features(frame, first_state, 3.0)
    first_capacity = capacity_expansion(first_state, 6)
    first = vcos_signal(
        first_features,
        first_capacity,
        coherence_threshold=0.80,
        capacity_ratio=1.50,
    )[decision]

    changed = frame.copy()
    future = np.arange(len(frame)) > decision
    changed.loc[future, ["open", "high", "low", "close"]] *= 4.0
    changed.loc[future, ["volume", "quote_volume"]] *= 7.0
    second_state = build_seasonal_state(changed, 2)
    second_features = build_bucket_features(changed, second_state, 3.0)
    second_capacity = capacity_expansion(second_state, 6)
    second = vcos_signal(
        second_features,
        second_capacity,
        coherence_threshold=0.80,
        capacity_ratio=1.50,
    )[decision]

    assert first == second == 1.0


def test_seasonal_profile_excludes_the_current_utc_day() -> None:
    frame, _decision = _frame()
    state = build_seasonal_state(frame, 2)
    changed = frame.copy()
    changed.iloc[2 * BARS_PER_DAY :, changed.columns.get_loc("volume")] *= 100.0
    changed_state = build_seasonal_state(changed, 2)

    np.testing.assert_array_equal(state.profiles[2], changed_state.profiles[2])
