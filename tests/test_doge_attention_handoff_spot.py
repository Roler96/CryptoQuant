"""Causality and contract tests for the DOGE spot attention strategy."""

from typing import cast

import numpy as np
import pandas as pd
import pandas.testing as pdt
import pytest

from cryptoquant.engine.backtest import BacktestEngine
from cryptoquant.exceptions import StrategyError
from cryptoquant.risk.sizer import FixedSizer
from strategies.doge_attention_handoff_spot import DogeAttentionHandoffSpot


def _panel(n: int = 2300, event_at: int | None = None) -> pd.DataFrame:
    index = pd.date_range("2025-01-01", periods=n, freq="1h")
    doge = np.full(n, 0.20)
    btc = np.full(n, 100.0)
    swap_volume = np.full(n, 100.0)
    if event_at is not None:
        btc[event_at:] = 85.0
        swap_volume[event_at - 5 : event_at + 1] = 250.0
        # Give the trade a deterministic positive path after the entry.
        doge[event_at + 1 :] = np.linspace(0.20, 0.23, n - event_at - 1)
    return pd.DataFrame(
        {
            "open": doge,
            "high": doge * 1.01,
            "low": doge * 0.99,
            "close": doge,
            "volume": np.full(n, 100.0),
            "swap_volume": swap_volume,
            "btc_close": btc,
        },
        index=index,
    )


def test_declares_spot_context_and_frozen_time_exit():
    strategy = DogeAttentionHandoffSpot()

    assert strategy.timeframe == "1h"
    assert strategy.signal_is_position is False
    assert strategy.max_hold_bars == 12
    assert [market.alias for market in strategy.context_markets] == ["swap", "btc"]
    assert strategy.context_markets[0].historical_symbol == "DOGE-USDT-SWAP"


def test_extreme_btc_shock_needs_positive_swap_participation():
    event_at = 2250
    panel = _panel(event_at=event_at)
    strategy = DogeAttentionHandoffSpot()

    signal = strategy.generate_signal(panel)
    without_handoff = panel.copy()
    without_handoff["swap_volume"] = without_handoff["volume"]

    assert signal.iloc[event_at] == 1
    assert strategy.generate_signal(without_handoff).sum() == 0


def test_fixed_swap_contract_multiplier_cannot_change_signal():
    panel = _panel(n=2400, event_at=2250)
    strategy = DogeAttentionHandoffSpot()
    scaled = panel.copy()
    scaled["swap_volume"] *= 1000

    pdt.assert_series_equal(
        strategy.generate_signal(panel),
        strategy.generate_signal(scaled),
    )


def test_btc_gap_disables_the_whole_shock_window():
    event_at = 2250
    panel = _panel(event_at=event_at)
    panel.iloc[event_at - 2, panel.columns.get_loc("btc_close")] = np.nan

    features = DogeAttentionHandoffSpot().build_features(panel)

    assert not bool(features["btc_window_complete"].iloc[event_at])
    assert not bool(features["raw_event"].iloc[event_at])


def test_future_mutation_cannot_change_past_features_or_signals():
    event_at = 2250
    panel = _panel(n=2400, event_at=event_at)
    strategy = DogeAttentionHandoffSpot()
    cutoff = panel.index[2300]
    before_features = strategy.build_features(panel).loc[:cutoff]
    before_signal = strategy.generate_signal(panel).loc[:cutoff]

    mutated = panel.copy()
    future = mutated.index > cutoff
    mutated.loc[future, "btc_close"] *= 0.5
    mutated.loc[future, "swap_volume"] *= 100
    mutated.loc[future, "volume"] *= 0.01

    pdt.assert_frame_equal(
        before_features,
        strategy.build_features(mutated).loc[:cutoff],
    )
    pdt.assert_series_equal(
        before_signal,
        strategy.generate_signal(mutated).loc[:cutoff],
    )


def test_deployment_lookback_reconstructs_recent_cooldown_state():
    panel = _panel(n=2500, event_at=2470)
    strategy = DogeAttentionHandoffSpot()

    full = strategy.generate_signal(panel)
    rolling = strategy.generate_signal(panel.iloc[-strategy.min_bars :])

    pdt.assert_series_equal(full.iloc[-48:], rolling.iloc[-48:])
    assert set(full.unique()).issubset({0, 1})


def test_engine_trades_primary_doge_spot_next_open_for_twelve_hours():
    event_at = 2250
    panel = _panel(n=2300, event_at=event_at)
    strategy = DogeAttentionHandoffSpot()
    engine = BacktestEngine(
        initial_capital=10_000,
        commission=0.001,
        slippage=0.0005,
        sizer=FixedSizer(risk_pct=10, min_order=0),
    )

    result = engine.run(
        panel,
        strategy,
        symbol="DOGE/USDT",
        max_hold_bars=strategy.max_hold_bars,
    )

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.symbol == "DOGE/USDT"
    entry_time = cast(pd.Timestamp, panel.index[event_at + 1])
    exit_time = cast(pd.Timestamp, panel.index[event_at + 13])
    assert trade.entry_time == int(entry_time.timestamp() * 1000)
    assert trade.exit_time == int(exit_time.timestamp() * 1000)
    assert trade.hold_hours == 12
    assert trade.position_size == pytest.approx(1000.0)


def test_missing_context_and_invalid_params_fail_closed():
    panel = _panel().drop(columns="btc_close")
    with pytest.raises(StrategyError, match="Missing market-context"):
        DogeAttentionHandoffSpot().generate_signal(panel)
    with pytest.raises(StrategyError, match="between 0 and 0.5"):
        DogeAttentionHandoffSpot({"btc_shock_quantile": 0.5})
