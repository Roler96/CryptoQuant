"""Tests for VWAPATRTrend strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from cryptoquant.strategy.signals import atr, vwap
from research.backtest_vwap_atr import VWAPATRTrend


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
    """Create trending data with strong price rise and wide bars."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)
    trend = np.linspace(100.0, 300.0, n)
    noise = rng.normal(0, 1.0, n)
    close = trend + noise
    # Alternating bar ranges: wide bars trigger ATR expansion
    bar_range = np.where(np.arange(n) % 3 == 0, 8.0, 2.0)
    half_range = bar_range / 2
    return pd.DataFrame(
        {
            "open": close - half_range * 0.3,
            "high": close + half_range,
            "low": close - half_range,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


def _make_downtrend_df(n: int = 500) -> pd.DataFrame:
    """Create trending data with strong price decline and wide bars."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)
    trend = np.linspace(300.0, 100.0, n)
    noise = rng.normal(0, 1.0, n)
    close = trend + noise
    bar_range = np.where(np.arange(n) % 3 == 0, 8.0, 2.0)
    half_range = bar_range / 2
    return pd.DataFrame(
        {
            "open": close + half_range * 0.3,
            "high": close + half_range,
            "low": close - half_range,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


class TestVWAPATRTrend:
    """Tests for VWAPATRTrend strategy."""

    def test_initialization(self):
        """Strategy initializes with default params."""
        s = VWAPATRTrend({})
        assert s.name == "VWAPATRTrend"
        assert s.params["vwap_period"] == 20
        assert s.params["atr_period"] == 14
        assert s.params["expansion_mult"] == 1.5

    def test_custom_params(self):
        """Custom params override defaults."""
        s = VWAPATRTrend({"vwap_period": 10, "expansion_mult": 2.0})
        assert s.params["vwap_period"] == 10
        assert s.params["expansion_mult"] == 2.0
        assert s.params["atr_period"] == 14  # unchanged default

    def test_insufficient_bars(self):
        """Strategy raises StrategyError with too few bars."""
        s = VWAPATRTrend({})
        df = _make_flat_df(n=50)
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_flat_price_signal_valid(self):
        """Flat price produces valid signal format."""
        s = VWAPATRTrend({})
        df = _make_flat_df(n=500)
        signal = s.generate_signal(df)
        assert len(signal) == len(df)
        assert signal.dtype == int
        assert set(signal.unique()).issubset({-1, 0, 1})

    def test_uptrend_generates_long_signal(self):
        """Uptrend should generate long signals (close > VWAP + expansion)."""
        s = VWAPATRTrend({})
        df = _make_uptrend_df(n=500)
        signal = s.generate_signal(df)
        assert len(signal) == len(df)
        assert 1 in signal.values

    def test_downtrend_generates_short_signal(self):
        """Downtrend should generate short signals."""
        s = VWAPATRTrend({})
        df = _make_downtrend_df(n=500)
        signal = s.generate_signal(df)
        assert len(signal) == len(df)
        assert -1 in signal.values

    def test_vwap_indicator_computes(self):
        """VWAP indicator produces valid output."""
        df = _make_uptrend_df(n=500)
        result = vwap(df, period=20)
        assert len(result) == len(df)
        assert result.iloc[100:].notna().any()

    def test_atr_indicator_computes(self):
        """ATR indicator produces valid output."""
        df = _make_uptrend_df(n=500)
        result = atr(df, period=14)
        assert len(result) == len(df)
        assert result.iloc[100:].notna().any()
