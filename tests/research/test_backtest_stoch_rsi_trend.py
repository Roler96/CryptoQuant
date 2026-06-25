"""Tests for StochRSITrend strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_stoch_rsi_trend import StochRSITrend


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


def _make_stoch_crossover_df(n: int = 500) -> pd.DataFrame:
    """Create data that triggers Stochastic %K/%D crossover signals.

    Pattern (repeating):
    - 10 bars: gentle uptrend (close climbs slowly, %K crosses above %D)
    - 10 bars: gentle downtrend (close falls slowly, %K crosses below %D)
    This creates periodic crossovers with the price above EMA200 overall.
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)

    close = np.zeros(n)
    base = 150.0  # well above EMA200 starting from ~100
    i = 0
    while i < n:
        # 10 bars gentle uptrend
        for _ in range(10):
            if i >= n:
                break
            base += rng.uniform(0.05, 0.3)
            noise = rng.normal(0, 0.05)
            close[i] = base + noise
            i += 1
        # 10 bars gentle downtrend
        for _ in range(10):
            if i >= n:
                break
            base -= rng.uniform(0.05, 0.3)
            noise = rng.normal(0, 0.05)
            close[i] = base + noise
            i += 1

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


def _make_downtrend_stoch_df(n: int = 500) -> pd.DataFrame:
    """Create data in downtrend below EMA200 with Stochastic crossovers.

    Price trends down from 95 to 70 (below EMA200), with periodic
    Stochastic %K/%D crossovers generating short entry signals.
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)

    close = np.zeros(n)
    base = 95.0  # starts below EMA200 starting from ~100
    i = 0
    while i < n:
        # 10 bars gentle downtrend (continues below EMA200)
        for _ in range(10):
            if i >= n:
                break
            base -= rng.uniform(0.05, 0.3)
            noise = rng.normal(0, 0.05)
            close[i] = base + noise
            i += 1
        # 10 bars gentle uptrend (still below EMA200)
        for _ in range(10):
            if i >= n:
                break
            base += rng.uniform(0.05, 0.3)
            noise = rng.normal(0, 0.05)
            close[i] = base + noise
            i += 1

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


class TestStochRSITrend:
    """Tests for the StochRSITrend strategy."""

    def test_default_params_instantiation(self):
        """Strategy can be instantiated with default parameters."""
        s = StochRSITrend()
        assert s.name == "StochRSITrend"
        assert s.timeframe == "1h"
        assert s.min_bars == 250
        assert s.version == "1.0.0"
        assert s.params["k_period"] == 14
        assert s.params["d_period"] == 3
        assert s.params["trend_period"] == 200

    def test_custom_params_instantiation(self):
        """Strategy can be instantiated with custom parameters."""
        s = StochRSITrend(
            params={"k_period": 10, "d_period": 5, "trend_period": 100}
        )
        assert s.params["k_period"] == 10
        assert s.params["d_period"] == 5
        assert s.params["trend_period"] == 100

    def test_generate_signal_returns_correct_shape(self):
        """generate_signal() returns Series with correct shape and types."""
        df = _make_flat_df(500)
        s = StochRSITrend()
        signal = s.generate_signal(df)

        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert (signal.index == df.index).all()
        assert signal.dtype == int

    def test_signal_values_valid(self):
        """Signal values are only -1, 0, 1."""
        df = _make_stoch_crossover_df(500)
        s = StochRSITrend()
        signal = s.generate_signal(df)
        unique_vals = set(signal.unique())
        assert unique_vals.issubset({-1, 0, 1})

    def test_insufficient_bars_raises(self):
        """Short DataFrame raises StrategyError via preprocess."""
        df = _make_flat_df(100)
        s = StochRSITrend()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_missing_columns_raises(self):
        """DataFrame missing required columns raises StrategyError."""
        df = pd.DataFrame(
            {"close": [100.0] * 500},
            index=pd.date_range("2024-01-01", periods=500, freq="1h"),
        )
        s = StochRSITrend()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_uptrend_produces_long_signals(self):
        """Uptrend data with stoch crossovers should produce long signals."""
        df = _make_stoch_crossover_df(500)
        s = StochRSITrend()
        signal = s.generate_signal(df)
        assert (signal == 1).any()

    def test_downtrend_produces_short_signals(self):
        """Downtrend data with stoch crossovers should produce short signals."""
        df = _make_downtrend_stoch_df(500)
        s = StochRSITrend()
        signal = s.generate_signal(df)
        assert (signal == -1).any()
