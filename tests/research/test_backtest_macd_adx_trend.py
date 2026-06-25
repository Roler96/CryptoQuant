"""Tests for MacdAdxTrend strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_macd_adx_trend import MacdAdxTrend


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
    """Create data with a sustained uptrend to trigger MACD crossover + ADX > 25."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    # Steady uptrend with enough range for ADX to rise
    close = 100.0 + np.cumsum(np.random.default_rng(42).normal(0.15, 0.5, n))
    close = np.maximum.accumulate(close)  # never dips, strong trend
    high = close + 1.0
    low = close - 1.0
    volume = np.full(n, 1000.0)
    return pd.DataFrame(
        {"open": close - 0.1, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


def _make_downtrend_df(n: int = 500) -> pd.DataFrame:
    """Create data with a sustained downtrend to trigger MACD crossover + ADX > 25."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    # Steady downtrend
    close = 100.0 - np.cumsum(np.random.default_rng(42).normal(0.15, 0.5, n))
    close = np.minimum.accumulate(close)
    high = close + 1.0
    low = close - 1.0
    volume = np.full(n, 1000.0)
    return pd.DataFrame(
        {"open": close - 0.1, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


class TestMacdAdxTrend:
    """Tests for the MacdAdxTrend strategy."""

    def test_default_params_instantiation(self):
        """Strategy can be instantiated with default parameters."""
        s = MacdAdxTrend()
        assert s.name == "MacdAdxTrend"
        assert s.timeframe == "1h"
        assert s.min_bars == 60
        assert s.version == "1.0.0"
        assert s.params["macd_fast"] == 12
        assert s.params["macd_slow"] == 26
        assert s.params["macd_signal"] == 9
        assert s.params["adx_period"] == 14
        assert s.params["adx_threshold"] == 25
        assert s.params["adx_exit_threshold"] == 20

    def test_custom_params_instantiation(self):
        """Strategy can be instantiated with custom parameters."""
        s = MacdAdxTrend(
            params={"macd_fast": 8, "adx_threshold": 20}
        )
        assert s.params["macd_fast"] == 8
        assert s.params["adx_threshold"] == 20
        # Unchanged defaults
        assert s.params["macd_slow"] == 26
        assert s.params["adx_period"] == 14

    def test_generate_signal_returns_correct_shape(self):
        """generate_signal() returns Series with correct shape and types."""
        df = _make_flat_df(500)
        s = MacdAdxTrend()
        signal = s.generate_signal(df)

        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert (signal.index == df.index).all()
        assert signal.dtype == int

    def test_signal_values_valid(self):
        """Signal values are only -1, 0, 1."""
        df = _make_uptrend_df(500)
        s = MacdAdxTrend()
        signal = s.generate_signal(df)
        unique_vals = set(signal.unique())
        assert unique_vals.issubset({-1, 0, 1})

    def test_insufficient_bars_raises(self):
        """Short DataFrame raises StrategyError via preprocess."""
        df = _make_flat_df(30)  # fewer than min_bars=60
        s = MacdAdxTrend()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_missing_columns_raises(self):
        """DataFrame missing required columns raises StrategyError."""
        df = pd.DataFrame(
            {"close": [100.0] * 500},
            index=pd.date_range("2024-01-01", periods=500, freq="1h"),
        )
        s = MacdAdxTrend()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_uptrend_produces_signal(self):
        """In a sustained uptrend, MACD crossover + ADX should produce signals."""
        df = _make_uptrend_df(500)
        s = MacdAdxTrend()
        signal = s.generate_signal(df)
        assert (signal != 0).any()

    def test_downtrend_produces_signal(self):
        """In a sustained downtrend, MACD crossover + ADX should produce signals."""
        df = _make_downtrend_df(500)
        s = MacdAdxTrend()
        signal = s.generate_signal(df)
        assert (signal != 0).any()
