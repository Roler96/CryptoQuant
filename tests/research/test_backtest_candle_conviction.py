"""Tests for CandleConvictionBreakout strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_candle_conviction import CandleConvictionBreakout


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


def _make_high_conviction_uptrend_df(n: int = 500) -> pd.DataFrame:
    """Create data with large bullish bodies in uptrend to trigger conviction entry.

    Large bodies (close - open = 3.0) with small wicks (range = 4.0) give
    body_ratio ≈ 0.75, well above the 0.55 threshold.
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)

    close = np.zeros(n)
    base = 100.0
    for i in range(n):
        if i % 3 == 0:
            base += rng.uniform(2.0, 5.0)  # conviction bars
        else:
            base += rng.uniform(0.0, 0.5)  # drift bars
        noise = rng.normal(0, 0.3)
        close[i] = base + noise

    body = np.full(n, 3.0)  # large bullish bodies
    open_vals = close - body
    high = close + 0.5
    low = open_vals - 0.5
    return pd.DataFrame(
        {
            "open": open_vals,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 2000.0),
        },
        index=dates,
    )


def _make_high_conviction_downtrend_df(n: int = 500) -> pd.DataFrame:
    """Create data with large bearish bodies in downtrend for short entry testing."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)

    close = np.zeros(n)
    base = 200.0
    for i in range(n):
        if i % 3 == 0:
            base -= rng.uniform(2.0, 5.0)  # conviction bars
        else:
            base -= rng.uniform(0.0, 0.5)  # drift bars
        noise = rng.normal(0, 0.3)
        close[i] = base + noise

    body = np.full(n, 3.0)  # large bearish bodies
    open_vals = close + body
    high = open_vals + 0.5
    low = close - 0.5
    return pd.DataFrame(
        {
            "open": open_vals,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 2000.0),
        },
        index=dates,
    )


class TestCandleConvictionBreakout:
    """Tests for the CandleConvictionBreakout strategy."""

    def test_default_params_instantiation(self):
        """Strategy can be instantiated with default parameters."""
        s = CandleConvictionBreakout()
        assert s.name == "CandleConvictionBreakout"
        assert s.timeframe == "1h"
        assert s.min_bars == 280
        assert s.version == "1.0.0"
        assert s.params["body_lookback"] == 14
        assert s.params["threshold"] == 0.55
        assert s.params["exit_threshold"] == 0.35
        assert s.params["trend_period"] == 200

    def test_custom_params_instantiation(self):
        """Strategy can be instantiated with custom parameters."""
        s = CandleConvictionBreakout(
            params={"body_lookback": 10, "threshold": 0.60, "exit_threshold": 0.30}
        )
        assert s.params["body_lookback"] == 10
        assert s.params["threshold"] == 0.60
        assert s.params["exit_threshold"] == 0.30

    def test_generate_signal_returns_correct_shape(self):
        """generate_signal() returns Series with correct shape and types."""
        df = _make_flat_df(500)
        s = CandleConvictionBreakout()
        signal = s.generate_signal(df)

        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert (signal.index == df.index).all()
        assert signal.dtype == int

    def test_signal_values_valid(self):
        """Signal values are only -1, 0, 1."""
        df = _make_high_conviction_uptrend_df(500)
        s = CandleConvictionBreakout()
        signal = s.generate_signal(df)
        unique_vals = set(signal.unique())
        assert unique_vals.issubset({-1, 0, 1})

    def test_insufficient_bars_raises(self):
        """Short DataFrame raises StrategyError via preprocess."""
        df = _make_flat_df(200)
        s = CandleConvictionBreakout()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_missing_columns_raises(self):
        """DataFrame missing required columns raises StrategyError."""
        df = pd.DataFrame(
            {"close": [100.0] * 500},
            index=pd.date_range("2024-01-01", periods=500, freq="1h"),
        )
        s = CandleConvictionBreakout()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_uptrend_produces_long_signals(self):
        """Uptrend with conviction bars should produce long signals."""
        df = _make_high_conviction_uptrend_df(500)
        s = CandleConvictionBreakout()
        signal = s.generate_signal(df)
        assert (signal == 1).any()

    def test_downtrend_produces_short_signals(self):
        """Downtrend with conviction bars should produce short signals."""
        df = _make_high_conviction_downtrend_df(500)
        s = CandleConvictionBreakout()
        signal = s.generate_signal(df)
        assert (signal == -1).any()
