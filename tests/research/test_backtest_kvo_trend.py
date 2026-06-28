"""Tests for KVOTrend strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from cryptoquant.strategy.signals import kvo
from research.backtest_kvo_trend import KVOTrend


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


class TestKVOTrend:
    """Tests for KVOTrend strategy."""

    def test_initialization(self):
        """Strategy initializes with default params."""
        s = KVOTrend({})
        assert s.name == "KVOTrend"
        assert s.params["kvo_fast"] == 34
        assert s.params["kvo_slow"] == 55
        assert s.params["trend_period"] == 200

    def test_custom_params(self):
        """Custom params override defaults."""
        s = KVOTrend({"kvo_fast": 20, "kvo_slow": 40, "trend_period": 100})
        assert s.params["kvo_fast"] == 20
        assert s.params["kvo_slow"] == 40
        assert s.params["trend_period"] == 100

    def test_insufficient_bars(self):
        """Strategy raises StrategyError with too few bars."""
        s = KVOTrend({})
        df = _make_flat_df(n=50)
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_flat_price_signal_valid(self):
        """Flat price produces valid signal format."""
        s = KVOTrend({})
        df = _make_flat_df(n=500)
        signal = s.generate_signal(df)
        assert len(signal) == len(df)
        assert signal.dtype == int
        assert set(signal.unique()).issubset({-1, 0, 1})

    def test_uptrend_generates_long_signal(self):
        """Uptrend should generate long signals."""
        s = KVOTrend({})
        df = _make_uptrend_df(n=500)
        signal = s.generate_signal(df)
        assert len(signal) == len(df)
        assert 1 in signal.values

    def test_downtrend_generates_short_signal(self):
        """Downtrend should generate short signals."""
        s = KVOTrend({})
        df = _make_downtrend_df(n=500)
        signal = s.generate_signal(df)
        assert len(signal) == len(df)
        assert -1 in signal.values

    def test_kvo_indicator_output(self):
        """KVO indicator produces valid DataFrame with kvo and zero columns."""
        df = _make_uptrend_df(n=500)
        result = kvo(df, fast=34, slow=55)
        assert "kvo" in result.columns
        assert "zero" in result.columns
        assert len(result) == len(df)
        # KVO should not be all-NaN after warmup
        assert result["kvo"].iloc[200:].notna().any()
