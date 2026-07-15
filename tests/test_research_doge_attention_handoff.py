"""Causality and execution tests for the DOGE research harness."""

from typing import cast

import numpy as np
import pandas as pd
import pandas.testing as pdt
import pytest

from research_doge_attention_handoff import (
    MarketSnapshot,
    SignalSpec,
    apply_cooldown,
    assert_production_signal_parity,
    build_event_signal,
    build_features,
    evaluate,
)


def _bars(
    index: pd.DatetimeIndex,
    close: np.ndarray | None = None,
    volume: np.ndarray | None = None,
) -> pd.DataFrame:
    values = np.ones(len(index)) if close is None else np.asarray(close, dtype=float)
    volumes = (
        np.full(len(index), 100.0)
        if volume is None
        else np.asarray(volume, dtype=float)
    )
    return pd.DataFrame(
        {
            "open": values,
            "high": values * 1.01,
            "low": values * 0.99,
            "close": values,
            "volume": volumes,
        },
        index=index,
    )


def _snapshot(length: int = 300) -> MarketSnapshot:
    index = pd.date_range("2020-01-01", periods=length, freq="1h")
    doge = np.exp(np.linspace(0, 0.2, length))
    btc = np.exp(np.linspace(10, 10.1, length))
    return MarketSnapshot(
        doge_spot=_bars(index, doge),
        doge_swap=_bars(index, doge * 1.001),
        btc_spot=_bars(index, btc),
    )


def _small_spec(**overrides) -> SignalSpec:
    values = {
        "btc_shock_hours": 3,
        "btc_shock_quantile": 0.1,
        "shock_history_hours": 48,
        "shock_min_history_hours": 24,
        "volume_block_hours": 3,
        "attention_baseline_hours": 12,
        "hold_hours": 4,
        "cooldown_hours": 10,
    }
    values.update(overrides)
    return SignalSpec(**values)


def test_future_mutation_cannot_change_past_features():
    snapshot = _snapshot()
    spec = _small_spec()
    original = build_features(snapshot, spec)

    cutoff = snapshot.doge_spot.index[199]
    changed_swap = snapshot.doge_swap.copy()
    changed_btc = snapshot.btc_spot.copy()
    changed_swap.loc[changed_swap.index > cutoff, ["close", "volume"]] *= 50
    changed_btc.loc[changed_btc.index > cutoff, "close"] *= 0.25
    changed = build_features(
        MarketSnapshot(snapshot.doge_spot, changed_swap, changed_btc),
        spec,
    )

    pdt.assert_frame_equal(original.loc[:cutoff], changed.loc[:cutoff])


def test_attention_baseline_does_not_overlap_current_volume_block():
    snapshot = _snapshot(120)
    spec = SignalSpec(
        btc_shock_hours=3,
        btc_shock_quantile=0.1,
        shock_history_hours=48,
        shock_min_history_hours=24,
        volume_block_hours=6,
        attention_baseline_hours=24,
        hold_hours=4,
        cooldown_hours=10,
    )
    target_position = 80
    target = snapshot.doge_spot.index[target_position]
    baseline_features = build_features(snapshot, spec)

    changed_swap = snapshot.doge_swap.copy()
    changed_swap.iloc[target_position - 5 : target_position + 1, 4] *= 20
    changed_features = build_features(
        MarketSnapshot(snapshot.doge_spot, changed_swap, snapshot.btc_spot),
        spec,
    )

    old_baseline = (
        baseline_features.loc[target, "log_volume_ratio"]
        - baseline_features.loc[target, "attention"]
    )
    new_baseline = (
        changed_features.loc[target, "log_volume_ratio"]
        - changed_features.loc[target, "attention"]
    )
    assert new_baseline == pytest.approx(old_baseline)
    assert changed_features.loc[target, "attention"] > baseline_features.loc[
        target, "attention"
    ]


def test_missing_btc_inside_shock_window_disables_event():
    snapshot = _snapshot(120)
    spec = _small_spec()
    target_position = 90
    target = snapshot.btc_spot.index[target_position]
    missing_btc = snapshot.btc_spot.copy()
    missing_btc.iloc[target_position - 1] = np.nan
    features = build_features(
        MarketSnapshot(snapshot.doge_spot, snapshot.doge_swap, missing_btc),
        spec,
    )

    assert not bool(features.loc[target, "btc_window_complete"])
    assert build_event_signal(features).loc[target] == 0


def test_cooldown_is_signal_to_signal_and_rejects_unfinishable_trade():
    index = pd.date_range("2020-01-01", periods=100, freq="1h")
    events = pd.Series(0, index=index, dtype=int)
    events.iloc[[0, 10, 48, 96]] = 1
    selected = apply_cooldown(events, SignalSpec())

    assert list(np.flatnonzero(selected.to_numpy())) == [0, 48]
    production = apply_cooldown(
        events,
        SignalSpec(),
        require_complete_trade=False,
    )
    assert list(np.flatnonzero(production.to_numpy())) == [0, 48, 96]


def test_backtest_enters_next_open_and_exits_after_frozen_hold():
    index = pd.date_range("2020-01-01", periods=50, freq="1h")
    prices = np.linspace(1.0, 1.49, len(index))
    bars = _bars(index, prices)
    snapshot = MarketSnapshot(bars, bars.copy(), _bars(index, prices * 100))
    spec = _small_spec(hold_hours=4, cooldown_hours=10)
    events = pd.Series(0, index=index, dtype=int)
    signal_position = 10
    events.iloc[signal_position] = 1

    result = evaluate(
        snapshot,
        events,
        spec,
        cast(pd.Timestamp, index[0]),
        cast(pd.Timestamp, index[-1] + pd.Timedelta(hours=1)),
        label="synthetic",
        commission_bps=0,
        slippage_bps=0,
    )
    entry_position = signal_position + 1
    exit_position = entry_position + spec.hold_hours
    expected_return_pct = (
        bars["open"].iloc[exit_position] / bars["open"].iloc[entry_position] - 1
    ) * 100

    assert result.trades == 1
    assert result.return_pct == pytest.approx(expected_return_pct, abs=1e-4)


def test_shipped_strategy_matches_frozen_research_signal():
    length = 2300
    event_at = 2250
    index = pd.date_range("2020-01-01", periods=length, freq="1h")
    doge = np.full(length, 0.2)
    btc = np.full(length, 100.0)
    btc[event_at:] = 85.0
    spot_volume = np.full(length, 100.0)
    swap_volume = np.full(length, 100.0)
    swap_volume[event_at - 5 : event_at + 1] = 250.0
    snapshot = MarketSnapshot(
        _bars(index, doge, spot_volume),
        _bars(index, doge, swap_volume),
        _bars(index, btc),
    )
    spec = SignalSpec()
    events = build_event_signal(build_features(snapshot, spec))

    assert_production_signal_parity(snapshot, events, spec)
