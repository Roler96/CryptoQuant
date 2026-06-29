"""Tests for HurstTrendFilter strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_hurst_trend_filter import HurstTrendFilter


def _make_flat_df(n: int = 500) -> pd.DataFrame:
    """Create a flat-price OHLCV DataFrame for testing."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = np.full(n, 100.0)
    high = close + 0.5
    low = close - 0.5
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


def _make_strong_uptrend_df(n: int = 500) -> pd.DataFrame:
    """Create data with strong uptrend for long entry testing.

    Decline below EMA50 for 110 bars (no cross_up possible), then sharply
    reverse and sustain a strong uptrend so Hurst stays > 0.55.
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)

    close = np.zeros(n)
    # Decline from 100 to ~85 in 110 bars (below EMA) — no cross_up possible
    base = 100.0
    for i in range(110):
        base -= 0.14
        noise = rng.normal(0, 0.3)
        close[i] = base + noise
    # Sharp reversal and sustained uptrend
    for i in range(110, n):
        base += 0.18
        noise = rng.normal(0, 0.4)
        close[i] = base + noise

    high = close + np.abs(rng.normal(1.5, 0.4, n))
    low = close - np.abs(rng.normal(1.0, 0.3, n))
    return pd.DataFrame(
        {
            "open": close - 0.2,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 5000.0),
        },
        index=dates,
    )


def _make_strong_downtrend_df(n: int = 500) -> pd.DataFrame:
    """Create data with strong downtrend for short entry testing.

    Rise above EMA50 for 110 bars (no cross_down possible), then sharply
    reverse and sustain a strong downtrend so Hurst stays > 0.55.
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)

    close = np.zeros(n)
    # Rise from 100 to ~115 in 110 bars (above EMA) — no cross_down possible
    base = 100.0
    for i in range(110):
        base += 0.14
        noise = rng.normal(0, 0.3)
        close[i] = base + noise
    # Sharp reversal and sustained downtrend
    for i in range(110, n):
        base -= 0.18
        noise = rng.normal(0, 0.4)
        close[i] = base + noise

    high = close + np.abs(rng.normal(1.0, 0.3, n))
    low = close - np.abs(rng.normal(1.5, 0.4, n))
    return pd.DataFrame(
        {
            "open": close + 0.2,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 5000.0),
        },
        index=dates,
    )


class TestHurstTrendFilter:
    """Tests for the HurstTrendFilter strategy."""

    def test_default_params_instantiation(self):
        """Strategy can be instantiated with default parameters."""
        s = HurstTrendFilter()
        assert s.name == "HurstTrendFilter"
        assert s.timeframe == "1h"
        assert s.min_bars == 100
        assert s.version == "1.0.0"
        assert s.params["ema_period"] == 50
        assert s.params["hurst_period"] == 100
        assert s.params["hurst_threshold"] == 0.55
        assert s.params["hurst_exit"] == 0.45

    def test_custom_params_instantiation(self):
        """Strategy can be instantiated with custom parameters."""
        s = HurstTrendFilter(params={
            "ema_period": 100,
            "hurst_period": 150,
            "hurst_threshold": 0.60,
            "hurst_exit": 0.40,
        })
        assert s.params["ema_period"] == 100
        assert s.params["hurst_period"] == 150
        assert s.params["hurst_threshold"] == 0.60
        assert s.params["hurst_exit"] == 0.40

    def test_generate_signal_returns_correct_shape(self):
        """generate_signal() returns Series with correct shape and types."""
        df = _make_flat_df(500)
        s = HurstTrendFilter()
        signal = s.generate_signal(df)

        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert (signal.index == df.index).all()
        assert signal.dtype == int

    def test_signal_values_valid(self):
        """Signal values are only -1, 0, 1."""
        df = _make_strong_uptrend_df(500)
        s = HurstTrendFilter()
        signal = s.generate_signal(df)
        unique_vals = set(signal.unique())
        assert unique_vals.issubset({-1, 0, 1})

    def test_insufficient_bars_raises(self):
        """Short DataFrame raises StrategyError via preprocess."""
        df = _make_flat_df(50)
        s = HurstTrendFilter()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_missing_columns_raises(self):
        """DataFrame missing required columns raises StrategyError."""
        df = pd.DataFrame(
            {"close": [100.0] * 500},
            index=pd.date_range("2024-01-01", periods=500, freq="1h"),
        )
        s = HurstTrendFilter()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_uptrend_produces_long_signals(self):
        """Strong uptrend data should produce long signals."""
        df = _make_strong_uptrend_df(500)
        s = HurstTrendFilter()
        signal = s.generate_signal(df)
        assert (signal == 1).any()

    def test_downtrend_produces_short_signals(self):
        """Strong downtrend data should produce short signals."""
        df = _make_strong_downtrend_df(500)
        s = HurstTrendFilter()
        signal = s.generate_signal(df)
        assert (signal == -1).any()
