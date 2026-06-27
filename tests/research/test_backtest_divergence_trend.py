"""Tests for DivergenceTrend strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_divergence_trend import DivergenceTrend


def _make_flat_df(n: int = 500) -> pd.DataFrame:
    """Create flat-price OHLCV DataFrame for testing."""
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


def _make_divergence_df(n: int = 800) -> pd.DataFrame:
    """Create data with clear RSI bull divergence.

    Phase 1 (0-199): Downtrend with declining price, RSI making higher lows.
    Phase 2 (200-399): Sharp reversal up — bullish divergence resolves.
    Phase 3 (400+): Continued uptrend.
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)

    close = np.full(n, np.nan)
    high = np.full(n, np.nan)
    low = np.full(n, np.nan)

    base = 100.0
    # Phase 1: Downtrend (price makes lower lows)
    for i in range(200):
        base -= 0.3 + abs(rng.normal(0, 0.15))
        close[i] = base
        high[i] = base + abs(rng.normal(0, 0.3))
        low[i] = base - abs(rng.normal(0, 0.5))

    # Phase 2: Reversal up with acceleration (bull divergence resolves)
    for i in range(200, 400):
        base += 0.8 + abs(rng.normal(0, 0.4))
        close[i] = base
        high[i] = base + abs(rng.normal(0, 0.6))
        low[i] = base - abs(rng.normal(0, 0.3))

    # Phase 3: Continued uptrend
    for i in range(400, n):
        base += 0.2 + rng.normal(0.1, 0.6)
        close[i] = base
        high[i] = base + abs(rng.normal(0, 0.8))
        low[i] = base - abs(rng.normal(0, 0.6))

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


class TestDivergenceTrend:
    """Tests for DivergenceTrend strategy."""

    def test_default_params_instantiation(self):
        """Strategy can be instantiated with default parameters."""
        s = DivergenceTrend()
        assert s.name == "DivergenceTrend"
        assert s.timeframe == "1h"
        assert s.min_bars == 300
        assert s.version == "1.0.0"
        assert s.params["rsi_period"] == 14
        assert s.params["pivot_lookback"] == 14
        assert s.params["trend_period"] == 200

    def test_custom_params_instantiation(self):
        """Strategy can be instantiated with custom parameters."""
        s = DivergenceTrend(
            params={"rsi_period": 7, "pivot_lookback": 10, "trend_period": 100}
        )
        assert s.params["rsi_period"] == 7
        assert s.params["pivot_lookback"] == 10
        assert s.params["trend_period"] == 100

    def test_generate_signal_returns_correct_shape(self):
        """generate_signal() returns Series with correct shape and types."""
        df = _make_flat_df(500)
        s = DivergenceTrend()
        signal = s.generate_signal(df)
        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert (signal.index == df.index).all()
        assert signal.dtype == int

    def test_signal_values_valid(self):
        """Signal values are only -1, 0, 1."""
        df = _make_divergence_df(600)
        s = DivergenceTrend()
        signal = s.generate_signal(df)
        unique_vals = set(signal.unique())
        assert unique_vals.issubset({-1, 0, 1})

    def test_insufficient_bars_raises(self):
        """Short DataFrame raises StrategyError via preprocess."""
        df = _make_flat_df(100)
        s = DivergenceTrend()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_missing_columns_raises(self):
        """DataFrame missing required columns raises StrategyError."""
        df = pd.DataFrame(
            {"close": [100.0] * 500},
            index=pd.date_range("2024-01-01", periods=500, freq="1h"),
        )
        s = DivergenceTrend()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_divergence_data_runs_without_error(self):
        """Strategy runs on divergence data without error."""
        df = _make_divergence_df(800)
        s = DivergenceTrend()
        signal = s.generate_signal(df)
        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert signal.dtype == int
        unique_vals = set(signal.unique())
        assert unique_vals.issubset({-1, 0, 1})
