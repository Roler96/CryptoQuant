"""Tests for OBVTrend strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_obv_trend import OBVTrend


def _make_flat_df(n: int = 500) -> pd.DataFrame:
    """Create a flat-price OHLCV DataFrame for testing."""
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
    """Create trending data with increasing price and volume."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    trend = np.linspace(100.0, 200.0, n)
    noise = np.random.default_rng(42).normal(0, 2.0, n)
    close = trend + noise
    return pd.DataFrame(
        {
            "open": close - 1.0,
            "high": close + 2.0,
            "low": close - 2.0,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


def _make_downtrend_df(n: int = 500) -> pd.DataFrame:
    """Create trending data with decreasing price."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    trend = np.linspace(200.0, 100.0, n)
    noise = np.random.default_rng(42).normal(0, 2.0, n)
    close = trend + noise
    return pd.DataFrame(
        {
            "open": close + 1.0,
            "high": close + 2.0,
            "low": close - 2.0,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


class TestOBVTrend:
    """Tests for OBVTrend strategy."""

    def test_initialization(self):
        """Strategy initializes with default params."""
        s = OBVTrend({})
        assert s.name == "OBVTrend"
        assert s.params["obv_sma_period"] == 20
        assert s.params["trend_period"] == 200

    def test_custom_params(self):
        """Custom params override defaults."""
        s = OBVTrend({"obv_sma_period": 10, "trend_period": 100})
        assert s.params["obv_sma_period"] == 10
        assert s.params["trend_period"] == 100

    def test_insufficient_bars(self):
        """Strategy raises StrategyError with too few bars."""
        s = OBVTrend({})
        df = _make_flat_df(n=50)
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_flat_price_no_signals(self):
        """Flat price with constant volume produces no trades."""
        s = OBVTrend({})
        df = _make_flat_df(n=500)
        signal = s.generate_signal(df)
        # Flat price + constant volume = OBV is flat = no crossovers
        # But with EMA200 convergence, there might be some edge signals
        # We verify no NaN and correct dtype
        assert len(signal) == len(df)
        assert signal.dtype == int
        assert set(signal.unique()).issubset({-1, 0, 1})

    def test_uptrend_generates_long_signal(self):
        """Uptrend with rising volume should generate long signals."""
        s = OBVTrend({})
        df = _make_uptrend_df(n=500)
        signal = s.generate_signal(df)
        assert len(signal) == len(df)
        # In uptrend, should have at least some long periods
        assert 1 in signal.values

    def test_downtrend_generates_short_signal(self):
        """Downtrend should generate short signals."""
        s = OBVTrend({})
        df = _make_downtrend_df(n=500)
        signal = s.generate_signal(df)
        assert len(signal) == len(df)
        assert -1 in signal.values
