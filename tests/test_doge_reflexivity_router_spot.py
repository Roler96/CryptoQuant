"""Causality and mechanism tests for the DOGE reflexivity router."""

import numpy as np
import pandas as pd
import pandas.testing as pdt
import pytest

from cryptoquant.exceptions import StrategyError
from strategies.doge_reflexivity_router_spot import DogeReflexivityRouterSpot


def _panel(n: int = 3100) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=n, freq="1h")
    phase = np.arange(n, dtype=float)
    btc_returns = 0.00025 * np.sin(phase / 11) + 0.00015 * np.cos(phase / 7)
    btc = 100.0 * np.exp(np.cumsum(btc_returns))
    doge = 0.20 * np.exp(np.cumsum(btc_returns))
    return pd.DataFrame(
        {
            "open": doge,
            "high": doge * 1.005,
            "low": doge * 0.995,
            "close": doge,
            "volume": np.full(n, 100.0),
            "swap_volume": np.full(n, 100.0),
            "btc_close": btc,
        },
        index=index,
    )


def _idio_event_panel(event_at: int = 3000) -> pd.DataFrame:
    panel = _panel()
    # Persistent derivatives participation, followed by a DOGE-only residual
    # shock. BTC itself remains on its ordinary deterministic path.
    panel.iloc[event_at - 6 : event_at + 1, panel.columns.get_loc("swap_volume")] = 300
    panel.iloc[event_at:, panel.columns.get_loc("close")] *= 0.82
    panel.iloc[event_at:, panel.columns.get_loc("open")] *= 0.82
    panel.iloc[event_at:, panel.columns.get_loc("high")] *= 0.82
    panel.iloc[event_at:, panel.columns.get_loc("low")] *= 0.82
    return panel


def test_declares_paper_spot_execution_contract():
    strategy = DogeReflexivityRouterSpot()

    assert strategy.execution_exchange == "okx"
    assert strategy.execution_symbol == "DOGE/USDT"
    assert strategy.execution_market_type == "spot"
    assert strategy.max_hold_bars == 12
    assert strategy.version.endswith("paper")
    assert [market.alias for market in strategy.context_markets] == ["swap", "btc"]


def test_doge_specific_residual_can_trigger_without_btc_crash():
    event_at = 3000
    panel = _idio_event_panel(event_at)

    features = DogeReflexivityRouterSpot().build_features(panel)
    signal = DogeReflexivityRouterSpot().generate_signal(panel)

    assert not bool(features["raw_systemic_event"].iloc[event_at])
    assert bool(features["raw_idiosyncratic_event"].iloc[event_at])
    assert signal.iloc[event_at] == 1


def test_idiosyncratic_leg_requires_persistent_derivatives_attention():
    event_at = 3000
    panel = _idio_event_panel(event_at)
    panel["swap_volume"] = panel["volume"]

    features = DogeReflexivityRouterSpot().build_features(panel)

    assert not bool(features["raw_idiosyncratic_event"].iloc[event_at])
    assert DogeReflexivityRouterSpot().generate_signal(panel).sum() == 0


def test_fixed_swap_volume_multiplier_does_not_change_router():
    panel = _idio_event_panel()
    scaled = panel.copy()
    scaled["swap_volume"] *= 1000
    strategy = DogeReflexivityRouterSpot()

    pdt.assert_series_equal(
        strategy.generate_signal(panel),
        strategy.generate_signal(scaled),
    )


def test_future_mutation_cannot_change_past_router_features():
    panel = _idio_event_panel()
    strategy = DogeReflexivityRouterSpot()
    cutoff = panel.index[3020]
    before = strategy.build_features(panel).loc[:cutoff]
    before_signal = strategy.generate_signal(panel).loc[:cutoff]

    changed = panel.copy()
    future = changed.index > cutoff
    changed.loc[future, "close"] *= 1.5
    changed.loc[future, "btc_close"] *= 0.7
    changed.loc[future, "swap_volume"] *= 20

    pdt.assert_frame_equal(before, strategy.build_features(changed).loc[:cutoff])
    pdt.assert_series_equal(
        before_signal,
        strategy.generate_signal(changed).loc[:cutoff],
    )


def test_lookback_reconstructs_recent_features_and_cooldown():
    panel = _panel(n=3600)
    event_at = 3500
    panel.iloc[event_at - 6 : event_at + 1, panel.columns.get_loc("swap_volume")] = 300
    for column in ("open", "high", "low", "close"):
        panel.iloc[event_at:, panel.columns.get_loc(column)] *= 0.82
    strategy = DogeReflexivityRouterSpot()

    full_features = strategy.build_features(panel)
    rolling_features = strategy.build_features(panel.iloc[-strategy.min_bars :])
    full_signal = strategy.generate_signal(panel)
    rolling_signal = strategy.generate_signal(panel.iloc[-strategy.min_bars :])

    pdt.assert_frame_equal(
        full_features.iloc[-48:],
        rolling_features.iloc[-48:],
        check_exact=False,
        rtol=1e-10,
        atol=1e-12,
    )
    pdt.assert_series_equal(full_signal.iloc[-48:], rolling_signal.iloc[-48:])


def test_invalid_residual_params_fail_closed():
    with pytest.raises(StrategyError, match="residual_quantile"):
        DogeReflexivityRouterSpot({"residual_quantile": 0.5})
    with pytest.raises(StrategyError, match="beta_min_history"):
        DogeReflexivityRouterSpot(
            {"beta_history_hours": 100, "beta_min_history_hours": 101}
        )


def test_live_lookback_tracks_explicit_history_overrides():
    strategy = DogeReflexivityRouterSpot(
        {
            "beta_history_hours": 800,
            "residual_history_hours": 2300,
            "residual_shock_hours": 8,
            "cooldown_hours": 60,
        }
    )

    assert strategy.min_bars == 800 + 2300 + 8 + 60 + 1
