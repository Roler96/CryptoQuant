"""Tests for RangeExpansionBreakout strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_range_expansion_breakout import RangeExpansionBreakout


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


def _make_uptrend_expansion_df(n: int = 500) -> pd.DataFrame:
    """Create data with breakout + bar expansion: sustained uptrend with spikes."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = np.full(n, 100.0)
    high = np.full(n, 100.5)
    low = np.full(n, 99.5)

    # Build trending price with breakout events
    base = 100.0
    for i in range(200, n):
        if i % 60 == 0:  # breakout every 60 bars
            base += 1.0  # step up
            close[i] = base + 1.0
            high[i] = base + 3.0  # large expansion bar
            low[i] = base - 0.5
        else:
            close[i] = base + np.sin(i * 0.1) * 0.2
            high[i] = close[i] + 0.3
            low[i] = close[i] - 0.3

    volume = np.full(n, 1000.0)
    return pd.DataFrame(
        {"open": close - 0.1, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


def _make_downtrend_expansion_df(n: int = 500) -> pd.DataFrame:
    """Create data with breakdown + bar expansion: sustained downtrend with spikes."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = np.full(n, 100.0)
    high = np.full(n, 100.5)
    low = np.full(n, 99.5)

    base = 100.0
    for i in range(200, n):
        if i % 60 == 0:
            base -= 1.0
            close[i] = base - 1.0
            high[i] = base + 0.5
            low[i] = base - 3.0  # large expansion bar
        else:
            close[i] = base + np.sin(i * 0.1) * 0.2
            high[i] = close[i] + 0.3
            low[i] = close[i] - 0.3

    volume = np.full(n, 1000.0)
    return pd.DataFrame(
        {"open": close - 0.1, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


class TestRangeExpansionBreakout:
    """Tests for the RangeExpansionBreakout strategy."""

    def test_default_params_instantiation(self):
        """Strategy can be instantiated with default parameters."""
        s = RangeExpansionBreakout()
        assert s.name == "RangeExpansionBreakout"
        assert s.timeframe == "1h"
        assert s.min_bars == 60
        assert s.version == "1.0.0"
        assert s.params["lookback"] == 20
        assert s.params["atr_period"] == 20
        assert s.params["expansion_mult"] == 1.5

    def test_custom_params_instantiation(self):
        """Strategy can be instantiated with custom parameters."""
        s = RangeExpansionBreakout(
            params={"lookback": 30, "expansion_mult": 2.0}
        )
        assert s.params["lookback"] == 30
        assert s.params["expansion_mult"] == 2.0
        # Unchanged defaults
        assert s.params["atr_period"] == 20

    def test_generate_signal_returns_correct_shape(self):
        """generate_signal() returns Series with correct shape and types."""
        df = _make_flat_df(500)
        s = RangeExpansionBreakout()
        signal = s.generate_signal(df)

        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert (signal.index == df.index).all()
        assert signal.dtype == int

    def test_signal_values_valid(self):
        """Signal values are only -1, 0, 1."""
        df = _make_uptrend_expansion_df(500)
        s = RangeExpansionBreakout()
        signal = s.generate_signal(df)
        unique_vals = set(signal.unique())
        assert unique_vals.issubset({-1, 0, 1})

    def test_insufficient_bars_raises(self):
        """Short DataFrame raises StrategyError via preprocess."""
        df = _make_flat_df(30)  # fewer than min_bars=60
        s = RangeExpansionBreakout()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_missing_columns_raises(self):
        """DataFrame missing required columns raises StrategyError."""
        df = pd.DataFrame(
            {"close": [100.0] * 500},
            index=pd.date_range("2024-01-01", periods=500, freq="1h"),
        )
        s = RangeExpansionBreakout()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_uptrend_breakout_produces_signal(self):
        """Sustained uptrend with expansion bars should produce signals."""
        df = _make_uptrend_expansion_df(500)
        s = RangeExpansionBreakout()
        signal = s.generate_signal(df)
        assert (signal != 0).any()

    def test_downtrend_breakdown_produces_signal(self):
        """Sustained downtrend with expansion bars should produce signals."""
        df = _make_downtrend_expansion_df(500)
        s = RangeExpansionBreakout()
        signal = s.generate_signal(df)
        assert (signal != 0).any()
