from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from research.explore_doge_5m_basis_shock_reversion import (
    BAR_MS,
    BsrParams,
    PairCosts,
    _add_causal_features,
    _funding_safe,
    _pair_episode_returns,
    _run,
)


def _pair_frame(
    spot_open: list[float],
    spot_close: list[float],
    swap_open: list[float],
    swap_close: list[float],
    start: str = "2021-01-01 01:00:00+00:00",
) -> pd.DataFrame:
    count = len(spot_open)
    index = pd.date_range(start, periods=count, freq="5min")
    ones = np.ones(count, dtype=float)
    return pd.DataFrame(
        {
            "spot_open": spot_open,
            "spot_high": np.maximum(spot_open, spot_close),
            "spot_low": np.minimum(spot_open, spot_close),
            "spot_close": spot_close,
            "spot_volume": ones,
            "swap_open": swap_open,
            "swap_high": np.maximum(swap_open, swap_close),
            "swap_low": np.minimum(swap_open, swap_close),
            "swap_close": swap_close,
            "swap_volume": ones,
        },
        index=index,
    )


def test_basis_baseline_uses_strictly_earlier_bars() -> None:
    spot = [100.0] * 5
    swap = [100.0, 100.1, 102.0, 101.0, 100.0]
    frame = _add_causal_features(
        _pair_frame(spot, spot, swap, swap),
        lookback=2,
    )
    historical_basis = np.log(np.asarray(swap[:2]) / 100.0)

    assert frame["basis_mean"].iloc[2] == pytest.approx(np.mean(historical_basis))
    assert frame["basis_std"].iloc[2] == pytest.approx(
        np.std(historical_basis, ddof=1)
    )


def test_basis_features_are_prefix_invariant() -> None:
    spot = [100.0] * 8
    swap = [100.0, 100.1, 100.2, 100.0, 100.3, 100.1, 100.0, 100.2]
    original = _pair_frame(spot, spot, swap, swap)
    changed = original.copy()
    changed.loc[changed.index[6]:, ["swap_open", "swap_close"]] *= 5.0

    original_features = _add_causal_features(original, lookback=3)
    changed_features = _add_causal_features(changed, lookback=3)

    np.testing.assert_allclose(
        original_features.loc[: original.index[5], ["basis_mean", "basis_std"]],
        changed_features.loc[: original.index[5], ["basis_mean", "basis_std"]],
        equal_nan=True,
    )


def test_flat_spread_loses_all_four_leg_costs() -> None:
    frame = _pair_frame(
        [100.0, 100.0],
        [100.0, 100.0],
        [100.0, 100.0],
        [100.0, 100.0],
    )

    result = _pair_episode_returns(
        frame,
        np.asarray([0]),
        np.asarray([1]),
        PairCosts(fee_bps=10.0, slippage_bps=5.0),
        leg_weight=0.5,
    )

    assert result[0] == pytest.approx(-0.003)


def test_signal_fills_both_legs_at_next_bar_open() -> None:
    spot_open = [100.0] * 7
    spot_close = [100.0] * 7
    swap_open = [100.0, 100.1, 102.0, 102.0, 100.0, 100.0, 100.0]
    swap_close = [100.0, 100.1, 102.0, 100.0, 100.0, 100.0, 100.0]
    frame = _add_causal_features(
        _pair_frame(spot_open, spot_close, swap_open, swap_close),
        lookback=2,
    )
    ts = (frame.index.astype("int64") // 1_000_000).to_numpy()
    params = BsrParams(
        lookback=2,
        entry_z=2.0,
        basis_floor=0.005,
        max_hold_bars=2,
        cooldown_bars=0,
    )

    run = _run(
        frame,
        params,
        PairCosts(),
        int(ts[0]),
        int(ts[-1] + BAR_MS),
    )

    assert len(run.episodes) == 1
    episode = run.episodes[0]
    assert episode.entry_index == 3
    assert episode.entry_ts == int(ts[3])
    assert episode.exit_index == 4
    assert episode.exit_ts == int(ts[4])
    assert episode.net_pnl > 0


def test_funding_guard_requires_exit_strictly_before_settlement() -> None:
    at_0655 = int(dt.datetime(2021, 1, 1, 6, 55, tzinfo=dt.UTC).timestamp() * 1000)
    at_0700 = int(dt.datetime(2021, 1, 1, 7, 0, tzinfo=dt.UTC).timestamp() * 1000)
    at_0800 = int(dt.datetime(2021, 1, 1, 8, 0, tzinfo=dt.UTC).timestamp() * 1000)

    assert _funding_safe(at_0655, max_hold_bars=12)
    assert not _funding_safe(at_0700, max_hold_bars=12)
    assert _funding_safe(at_0800, max_hold_bars=12)
