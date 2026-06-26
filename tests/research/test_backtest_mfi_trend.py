"""Tests for MFITrend strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_mfi_trend import MFITrend


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


def _make_uptrend_df(n: int = 500) -> pd.DataFrame:
    """Create data with uptrend + rising typical price for MFI bullish."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)

    close = np.zeros(n)
    base = 100.0
    for i in range(n):
        base += 0.10
        noise = rng.normal(0, 0.3)
        close[i] = base + noise

    # Rising typical price, higher volume → positive money flow
    volume = np.full(n, 5000.0)
    high = close + 1.5
    low = close - 0.8
    return pd.DataFrame(
        {
            "open": close - 0.2,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=dates,
    )


def _make_downtrend_df(n: int = 500) -> pd.DataFrame:
    """Create data with downtrend + falling typical price for MFI bearish."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)

    close = np.zeros(n)
    base = 200.0
    for i in range(n):
        base -= 0.10
        noise = rng.normal(0, 0.3)
        close[i] = base + noise

    # Falling typical price, higher volume → negative money flow
    volume = np.full(n, 5000.0)
    high = close + 0.8
    low = close - 1.5
    return pd.DataFrame(
        {
            "open": close + 0.2,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=dates,
    )


class TestMFITrend:
    """Tests for the MFITrend strategy."""

    def test_default_params_instantiation(self):
        """Strategy can be instantiated with default parameters."""
        s = MFITrend()
        assert s.name == "MFITrend"
        assert s.timeframe == "1h"
        assert s.min_bars == 200
        assert s.version == "1.0.0"
        assert s.params["mfi_period"] == 14
        assert s.params["trend_period"] == 200

    def test_custom_params_instantiation(self):
        """Strategy can be instantiated with custom parameters."""
        s = MFITrend(params={"mfi_period": 20, "trend_period": 100})
        assert s.params["mfi_period"] == 20
        assert s.params["trend_period"] == 100

    def test_generate_signal_returns_correct_shape(self):
        """generate_signal() returns Series with correct shape and types."""
        df = _make_flat_df(500)
        s = MFITrend()
        signal = s.generate_signal(df)

        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert (signal.index == df.index).all()
        assert signal.dtype == int

    def test_signal_values_valid(self):
        """Signal values are only -1, 0, 1."""
        df = _make_uptrend_df(500)
        s = MFITrend()
        signal = s.generate_signal(df)
        unique_vals = set(signal.unique())
        assert unique_vals.issubset({-1, 0, 1})

    def test_insufficient_bars_raises(self):
        """Short DataFrame raises StrategyError via preprocess."""
        df = _make_flat_df(150)
        s = MFITrend()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_missing_columns_raises(self):
        """DataFrame missing required columns raises StrategyError."""
        df = pd.DataFrame(
            {"close": [100.0] * 500},
            index=pd.date_range("2024-01-01", periods=500, freq="1h"),
        )
        s = MFITrend()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_uptrend_produces_long_signals(self):
        """Uptrend with rising typical price should produce long signals."""
        df = _make_uptrend_df(500)
        s = MFITrend()
        signal = s.generate_signal(df)
        assert (signal == 1).any()

    def test_downtrend_produces_short_signals(self):
        """Downtrend with falling typical price should produce short signals."""
        df = _make_downtrend_df(500)
        s = MFITrend()
        signal = s.generate_signal(df)
        assert (signal == -1).any()
