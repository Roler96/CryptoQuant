"""Tests for AdaptiveEmaVolRegime strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_adaptive_ema_vol_regime import (
    AdaptiveEmaVolRegime,
    rolling_percentile_rank,
)


def _make_flat_df(n: int = 500) -> pd.DataFrame:
    """Flat-price OHLCV DataFrame."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = np.full(n, 100.0)
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


def _make_uptrend_df(n: int = 500) -> pd.DataFrame:
    """Data with flat base then sharp rally — triggers EMA crossover."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.RandomState(42)
    close = np.full(n, 100.0)
    # Flat base for 200 bars (EMAs converge)
    close[:200] = 100.0 + rng.randn(200) * 0.3
    # Sharp rally at bar 250 triggers fast EMA to cross above slow EMA
    close[250:350] = 120.0 + rng.randn(100) * 0.3
    # Stay elevated
    close[350:] = 120.0 + rng.randn(150) * 0.5
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


def _make_volatile_uptrend_df(n: int = 500) -> pd.DataFrame:
    """Uptrend with large swings to trigger regime switching."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.RandomState(99)
    close = np.linspace(100, 150, n)
    noise = rng.randn(n) * 3.0  # higher volatility
    close = close + noise

    high = close + np.abs(rng.randn(n) * 2.0)
    low = close - np.abs(rng.randn(n) * 2.0)
    opens = close + rng.randn(n) * 0.5

    return pd.DataFrame(
        {
            "open": opens,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


class TestRollingPercentileRank:
    """Tests for the rolling_percentile_rank utility."""

    def test_output_shape(self):
        """Returns same index as input."""
        s = pd.Series(np.arange(200), index=pd.date_range("2024-01-01", periods=200, freq="1h"))
        result = rolling_percentile_rank(s, 50)
        assert len(result) == 200

    def test_monotonic_increasing(self):
        """Last value in increasing series = 100 (all earlier values smaller)."""
        s = pd.Series(np.arange(100, dtype=float))
        result = rolling_percentile_rank(s, 50)
        # After first 49 NaN, the 50th and beyond should be high
        assert result.iloc[-1] > 90  # nearly 100


class TestAdaptiveEmaVolRegime:
    """Tests for AdaptiveEmaVolRegime strategy."""

    def test_default_params_instantiation(self):
        s = AdaptiveEmaVolRegime()
        assert s.name == "AdaptiveEmaVolRegime"
        assert s.timeframe == "1h"
        assert s.min_bars == 200
        assert s.params["fast_high"] == 8
        assert s.params["slow_high"] == 21
        assert s.params["fast_low"] == 16
        assert s.params["slow_low"] == 34
        assert s.params["regime_threshold_pct"] == 70.0

    def test_custom_params_instantiation(self):
        s = AdaptiveEmaVolRegime(params={"fast_high": 6, "slow_high": 18})
        assert s.params["fast_high"] == 6
        assert s.params["slow_high"] == 18
        assert s.params["fast_low"] == 16  # unchanged default

    def test_generate_signal_correct_shape(self):
        df = _make_flat_df(500)
        s = AdaptiveEmaVolRegime()
        signal = s.generate_signal(df)
        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert (signal.index == df.index).all()
        assert signal.dtype == int

    def test_signal_values_valid(self):
        df = _make_volatile_uptrend_df(500)
        s = AdaptiveEmaVolRegime()
        signal = s.generate_signal(df)
        unique_vals = set(signal.unique())
        assert unique_vals.issubset({-1, 0, 1})

    def test_insufficient_bars_raises(self):
        df = _make_flat_df(50)
        s = AdaptiveEmaVolRegime()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_missing_columns_raises(self):
        df = pd.DataFrame(
            {"close": [100.0] * 500},
            index=pd.date_range("2024-01-01", periods=500, freq="1h"),
        )
        s = AdaptiveEmaVolRegime()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_uptrend_produces_long_signal(self):
        df = _make_uptrend_df(500)
        s = AdaptiveEmaVolRegime(params={"hysteresis_bars": 1})  # faster switching
        signal = s.generate_signal(df)
        assert (signal == 1).any(), f"Should produce at least one long signal. Signal values: {signal.value_counts().to_dict()}"

    def test_flat_market_no_excessive_signals(self):
        """Flat market should not produce more than a handful of signals."""
        df = _make_flat_df(500)
        s = AdaptiveEmaVolRegime()
        signal = s.generate_signal(df)
        # Count signal transitions (not just non-zero bars)
        changes = (signal.diff() != 0).sum()
        assert changes < 50, f"Too many signal transitions in flat market: {changes}"
