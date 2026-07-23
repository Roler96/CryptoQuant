from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.explore_doge_5m_basis_shock_reversion import BAR_MS, PairCosts
from research.explore_doge_5m_synchronized_impulse import (
    SicParams,
    _add_causal_features,
    _entry_side,
    _episode_returns_at,
    _run,
)


def _pair_frame(
    spot_open: list[float],
    spot_close: list[float],
    swap_open: list[float],
    swap_close: list[float],
    swap_volume: list[float] | None = None,
) -> pd.DataFrame:
    count = len(spot_open)
    index = pd.date_range(
        "2021-01-01 01:00:00+00:00", periods=count, freq="5min"
    )
    volume = np.ones(count) if swap_volume is None else np.asarray(swap_volume)
    return pd.DataFrame(
        {
            "spot_open": spot_open,
            "spot_high": np.maximum(spot_open, spot_close),
            "spot_low": np.minimum(spot_open, spot_close),
            "spot_close": spot_close,
            "spot_volume": np.ones(count),
            "swap_open": swap_open,
            "swap_high": np.maximum(swap_open, swap_close),
            "swap_low": np.minimum(swap_open, swap_close),
            "swap_close": swap_close,
            "swap_volume": volume,
        },
        index=index,
    )


def test_impulse_baselines_exclude_the_current_bar() -> None:
    swap = [100.0, 101.0, 102.0, 106.0, 106.0]
    volume = [1.0, 2.0, 3.0, 100.0, 1.0]
    params = SicParams(lookback=2, impulse_bars=1)
    frame = _add_causal_features(
        _pair_frame(swap, swap, swap, swap, volume),
        params,
    )
    past_returns = np.diff(np.log(np.asarray(swap[:3])))

    assert frame["sigma"].iloc[3] == pytest.approx(
        np.std(past_returns, ddof=1)
    )
    assert frame["volume_ratio"].iloc[3] == pytest.approx(100.0 / 2.5)


def test_impulse_features_are_prefix_invariant() -> None:
    values = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0]
    original = _pair_frame(values, values, values, values)
    changed = original.copy()
    changed.loc[changed.index[6]:, ["swap_close", "spot_close"]] *= 4.0
    params = SicParams(lookback=3, impulse_bars=1)

    left = _add_causal_features(original, params)
    right = _add_causal_features(changed, params)

    np.testing.assert_allclose(
        left.loc[: original.index[5], ["sigma", "shock_score", "volume_ratio"]],
        right.loc[: original.index[5], ["sigma", "shock_score", "volume_ratio"]],
        equal_nan=True,
    )


def test_flat_price_charges_symmetric_long_and_short_round_trip_costs() -> None:
    frame = _pair_frame(
        [100.0, 100.0],
        [100.0, 100.0],
        [100.0, 100.0],
        [100.0, 100.0],
    )
    entries = np.asarray([0, 0])
    exits = np.asarray([1, 1])
    sides = np.asarray([1.0, -1.0])

    returns = _episode_returns_at(
        frame,
        entries,
        exits,
        sides,
        PairCosts(fee_bps=10.0, slippage_bps=5.0),
        weight=0.5,
    )

    np.testing.assert_allclose(returns, [-0.0015, -0.0015])


def test_spot_must_confirm_the_swap_direction() -> None:
    assert _entry_side(4.0, 0.02, 0.01) == 1
    assert _entry_side(-4.0, -0.02, -0.01) == -1
    assert _entry_side(4.0, 0.02, -0.01) == 0


def test_signal_enters_next_open_and_exits_after_fixed_complete_bars() -> None:
    spot = [100.0, 101.0, 102.0, 105.0, 107.0, 108.0, 109.0, 109.0]
    swap = [100.0, 101.0, 102.0, 106.0, 108.0, 109.0, 110.0, 110.0]
    volume = [1.0, 1.0, 1.0, 10.0, 1.0, 1.0, 1.0, 1.0]
    frame = _add_causal_features(
        _pair_frame(spot, spot, swap, swap, volume),
        SicParams(
            lookback=2,
            impulse_bars=1,
            score_threshold=2.0,
            volume_ratio=2.0,
            hold_bars=2,
            cooldown_bars=0,
        ),
    )
    ts = (frame.index.astype("int64") // 1_000_000).to_numpy()
    params = SicParams(
        lookback=2,
        impulse_bars=1,
        score_threshold=2.0,
        volume_ratio=2.0,
        hold_bars=2,
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
    assert episode.side == 1
    assert episode.entry_index == 4
    assert episode.entry_ts == int(ts[4])
    assert episode.exit_index == 6
    assert episode.exit_ts == int(ts[6])
    assert episode.holding_bars == 2
    assert episode.net_pnl > 0
