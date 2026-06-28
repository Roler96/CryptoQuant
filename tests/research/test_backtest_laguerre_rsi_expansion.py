"""Tests for LaguerreRSIExpansion strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from cryptoquant.strategy.signals import atr, laguerre_rsi
from research.backtest_laguerre_rsi_expansion import LaguerreRSIExpansion


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


class TestLaguerreRSIExpansion:
    """Tests for LaguerreRSIExpansion strategy."""

    def test_initialization(self):
        """Strategy initializes with default params."""
        s = LaguerreRSIExpansion({})
        assert s.name == "LaguerreRSIExpansion"
        assert s.params["lrsi_period"] == 14
        assert s.params["lrsi_gamma"] == 0.5
        assert s.params["atr_period"] == 14
        assert s.params["atr_percentile"] == 80

    def test_custom_params(self):
        """Custom params override defaults."""
        s = LaguerreRSIExpansion({"lrsi_period": 10, "lrsi_gamma": 0.7})
        assert s.params["lrsi_period"] == 10
        assert s.params["lrsi_gamma"] == 0.7
        assert s.params["atr_period"] == 14  # unchanged default

    def test_insufficient_bars(self):
        """Strategy raises StrategyError with too few bars."""
        s = LaguerreRSIExpansion({})
        df = _make_flat_df(n=50)
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_flat_price_signal_valid(self):
        """Flat price produces valid signal format."""
        s = LaguerreRSIExpansion({})
        df = _make_flat_df(n=500)
        signal = s.generate_signal(df)
        assert len(signal) == len(df)
        assert signal.dtype == int
        assert set(signal.unique()).issubset({-1, 0, 1})

    def test_uptrend_generates_long_signal(self):
        """Uptrend should generate long signals."""
        s = LaguerreRSIExpansion({})
        df = _make_uptrend_df(n=500)
        signal = s.generate_signal(df)
        assert len(signal) == len(df)
        assert 1 in signal.values

    def test_laguerre_rsi_indicator_range(self):
        """Laguerre RSI produces valid 0-100 output."""
        df = _make_uptrend_df(n=500)
        result = laguerre_rsi(df["close"], period=14, gamma=0.5)
        assert len(result) == len(df)
        valid = result.dropna()
        assert len(valid) > 0
        assert valid.max() <= 100.01  # floating-point tolerance
        assert valid.min() >= -0.01

    def test_laguerre_rsi_invalid_gamma(self):
        """Laguerre RSI raises on invalid gamma."""
        df = _make_flat_df(n=200)
        with pytest.raises(ValueError):
            laguerre_rsi(df["close"], period=14, gamma=0)
        with pytest.raises(ValueError):
            laguerre_rsi(df["close"], period=14, gamma=1)
