"""Tests for EMACrossATRFilter strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_ema_cross_atr_filter import EMACrossATRFilter


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
    """Create data with a sharp price spike that triggers EMA crossover."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = np.full(n, 100.0)
    # Sharp sustained spike to force fast EMA to cross above slow EMA
    close[250:400] = 115.0

    high = close + 0.5
    low = close - 0.5
    opens = close - 0.1

    return pd.DataFrame(
        {
            "open": opens,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


def _make_downtrend_df(n: int = 500) -> pd.DataFrame:
    """Create data with a sharp price drop that triggers EMA crossover."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = np.full(n, 100.0)
    # Sharp sustained drop to force fast EMA to cross below slow EMA
    close[250:400] = 85.0

    high = close + 0.5
    low = close - 0.5
    opens = close - 0.1

    return pd.DataFrame(
        {
            "open": opens,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


class TestEMACrossATRFilter:
    """Tests for the EMACrossATRFilter strategy."""

    def test_default_params_instantiation(self):
        """Strategy can be instantiated with default parameters."""
        s = EMACrossATRFilter()
        assert s.name == "EMACrossATRFilter"
        assert s.timeframe == "1h"
        assert s.min_bars == 200
        assert s.version == "1.0.0"
        assert s.params["fast_period"] == 8
        assert s.params["slow_period"] == 21
        assert s.params["atr_period"] == 14
        assert s.params["atr_long_period"] == 50
        assert s.params["vol_threshold"] == 2.0

    def test_custom_params_instantiation(self):
        """Strategy can be instantiated with custom parameters."""
        s = EMACrossATRFilter(
            params={"fast_period": 6, "slow_period": 18, "vol_threshold": 1.5}
        )
        assert s.params["fast_period"] == 6
        assert s.params["slow_period"] == 18
        assert s.params["vol_threshold"] == 1.5
        # Unchanged defaults
        assert s.params["atr_period"] == 14

    def test_generate_signal_returns_correct_shape(self):
        """generate_signal() returns Series with correct shape and types."""
        df = _make_flat_df(500)
        s = EMACrossATRFilter()
        signal = s.generate_signal(df)

        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert (signal.index == df.index).all()
        assert signal.dtype == int

    def test_signal_values_valid(self):
        """Signal values are only -1, 0, 1."""
        df = _make_uptrend_df(500)
        s = EMACrossATRFilter()
        signal = s.generate_signal(df)
        unique_vals = set(signal.unique())
        assert unique_vals.issubset({-1, 0, 1})

    def test_insufficient_bars_raises(self):
        """Short DataFrame raises StrategyError via preprocess."""
        df = _make_flat_df(50)  # fewer than min_bars=200
        s = EMACrossATRFilter()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_missing_columns_raises(self):
        """DataFrame missing required columns raises StrategyError."""
        df = pd.DataFrame(
            {"close": [100.0] * 500},
            index=pd.date_range("2024-01-01", periods=500, freq="1h"),
        )
        s = EMACrossATRFilter()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_uptrend_produces_signal(self):
        """In a steady uptrend, EMA crossover should eventually produce signals."""
        df = _make_uptrend_df(500)
        s = EMACrossATRFilter()
        signal = s.generate_signal(df)
        # At least some non-zero signals in a clear uptrend
        assert (signal != 0).any()

    def test_downtrend_produces_signal(self):
        """In a steady downtrend, EMA crossover should eventually produce signals."""
        df = _make_downtrend_df(500)
        s = EMACrossATRFilter()
        signal = s.generate_signal(df)
        assert (signal != 0).any()
