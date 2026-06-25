"""Tests for ChannelBreakoutRSI strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_channel_breakout_rsi import ChannelBreakoutRSI


def _make_flat_df(n: int = 500) -> pd.DataFrame:
    """Create a flat-price OHLCV DataFrame for testing."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = np.full(n, 100.0)
    high = close + 0.5
    low = close - 0.5
    volume = np.full(n, 1000.0)
    return pd.DataFrame(
        {"open": close - 0.1, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


def _make_uptrend_df(n: int = 500) -> pd.DataFrame:
    """Create data with a strong sustained uptrend to trigger channel breakout + RSI > 50."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    # Strong sustained uptrend to push RSI well above 50
    close = 100.0 + np.linspace(0, 50, n)  # 100 → 150 over 500 bars
    close[300:320] = 160.0  # Extra spike to break above highest_high(30)
    high = close + 0.5
    low = close - 0.5
    volume = np.full(n, 1000.0)
    return pd.DataFrame(
        {"open": close - 0.1, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


def _make_downtrend_df(n: int = 500) -> pd.DataFrame:
    """Create data with a strong sustained downtrend to trigger channel breakdown + RSI < 50."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    # Strong sustained downtrend to push RSI well below 50
    close = 100.0 - np.linspace(0, 50, n)  # 100 → 50 over 500 bars
    close[300:320] = 40.0  # Extra drop to break below lowest_low(30)
    high = close + 0.5
    low = close - 0.5
    volume = np.full(n, 1000.0)
    return pd.DataFrame(
        {"open": close - 0.1, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


class TestChannelBreakoutRSI:
    """Tests for the ChannelBreakoutRSI strategy."""

    def test_default_params_instantiation(self):
        """Strategy can be instantiated with default parameters."""
        s = ChannelBreakoutRSI()
        assert s.name == "ChannelBreakoutRSI"
        assert s.timeframe == "1h"
        assert s.min_bars == 100
        assert s.version == "1.0.0"
        assert s.params["channel_period"] == 30
        assert s.params["rsi_period"] == 14
        assert s.params["rsi_threshold"] == 50
        assert s.params["sma_period"] == 20

    def test_custom_params_instantiation(self):
        """Strategy can be instantiated with custom parameters."""
        s = ChannelBreakoutRSI(
            params={"channel_period": 20, "rsi_threshold": 45}
        )
        assert s.params["channel_period"] == 20
        assert s.params["rsi_threshold"] == 45
        # Unchanged defaults
        assert s.params["rsi_period"] == 14
        assert s.params["sma_period"] == 20

    def test_generate_signal_returns_correct_shape(self):
        """generate_signal() returns Series with correct shape and types."""
        df = _make_flat_df(500)
        s = ChannelBreakoutRSI()
        signal = s.generate_signal(df)

        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert (signal.index == df.index).all()
        assert signal.dtype == int

    def test_signal_values_valid(self):
        """Signal values are only -1, 0, 1."""
        df = _make_uptrend_df(500)
        s = ChannelBreakoutRSI()
        signal = s.generate_signal(df)
        unique_vals = set(signal.unique())
        assert unique_vals.issubset({-1, 0, 1})

    def test_insufficient_bars_raises(self):
        """Short DataFrame raises StrategyError via preprocess."""
        df = _make_flat_df(50)  # fewer than min_bars=100
        s = ChannelBreakoutRSI()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_missing_columns_raises(self):
        """DataFrame missing required columns raises StrategyError."""
        df = pd.DataFrame(
            {"close": [100.0] * 500},
            index=pd.date_range("2024-01-01", periods=500, freq="1h"),
        )
        s = ChannelBreakoutRSI()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_uptrend_produces_signal(self):
        """In a sustained uptrend, channel breakout should produce signals."""
        df = _make_uptrend_df(500)
        s = ChannelBreakoutRSI()
        signal = s.generate_signal(df)
        assert (signal != 0).any()

    def test_downtrend_produces_signal(self):
        """In a sustained downtrend, channel breakdown should produce signals."""
        df = _make_downtrend_df(500)
        s = ChannelBreakoutRSI()
        signal = s.generate_signal(df)
        assert (signal != 0).any()
