"""Tests for SwingPivotBreakout strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_swing_pivot_breakout import SwingPivotBreakout


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


def _make_uptrend_with_pivots(n: int = 500) -> pd.DataFrame:
    """Create an uptrend with clear swing pivot structure.

    Price gradually rises, forming higher swing highs and higher
    swing lows — classic bullish market structure.
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)

    close = np.zeros(n)
    base = 100.0
    for i in range(n):
        # Slow uptrend with periodic pullbacks
        base += 0.1
        if i % 20 == 15:
            base -= 0.5  # Micro pullback
        close[i] = base + rng.normal(0, 0.3)

    bar_range = np.abs(rng.normal(1.0, 0.3, n)) + 0.5
    high = close + bar_range
    low = close - bar_range
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


def _make_downtrend_with_pivots(n: int = 500) -> pd.DataFrame:
    """Create a downtrend with clear swing pivot structure."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)

    close = np.zeros(n)
    base = 200.0
    for i in range(n):
        base -= 0.1
        if i % 20 == 15:
            base += 0.5  # Micro rally
        close[i] = base + rng.normal(0, 0.3)

    bar_range = np.abs(rng.normal(1.0, 0.3, n)) + 0.5
    high = close + bar_range
    low = close - bar_range
    return pd.DataFrame(
        {
            "open": close + 0.1,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


class TestSwingPivotBreakout:
    """Tests for the SwingPivotBreakout strategy."""

    def test_default_params_instantiation(self):
        """Strategy can be instantiated with default parameters."""
        s = SwingPivotBreakout()
        assert s.name == "SwingPivotBreakout"
        assert s.timeframe == "1h"
        assert s.params["pivot_window"] == 5
        assert s.params["atr_period"] == 14
        assert s.params["trailing_mult"] == 2.0

    def test_min_bars_raises(self):
        """Strategy raises StrategyError when df has fewer than min_bars."""
        s = SwingPivotBreakout()
        dates = pd.date_range("2024-01-01", periods=20, freq="1h")
        df = pd.DataFrame(
            {
                "open": 100.0, "high": 101.0, "low": 99.0,
                "close": 100.0, "volume": 1000.0,
            },
            index=dates,
        )
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_signal_shape(self):
        """Signal output matches input DataFrame shape."""
        df = _make_uptrend_with_pivots(500)
        s = SwingPivotBreakout()
        sig = s.generate_signal(df)
        assert len(sig) == len(df)
        assert sig.index.equals(df.index)
        assert sig.dtype in (int, np.int32, np.int64)

    def test_flat_market_no_trades(self):
        """In a completely flat market, no pivots are broken."""
        df = _make_flat_df(500)
        s = SwingPivotBreakout()
        sig = s.generate_signal(df)
        # Flat close + no pivot breakouts → should stay flat
        assert (sig == 0).all()

    def test_uptrend_generates_long_trades(self):
        """Uptrend with pivots should produce long entries."""
        df = _make_uptrend_with_pivots(500)
        s = SwingPivotBreakout()
        sig = s.generate_signal(df)
        assert 1 in sig.values
        long_count = (sig == 1).sum()
        short_count = (sig == -1).sum()
        # In uptrend, longs should dominate
        assert long_count > 0

    def test_downtrend_generates_short_trades(self):
        """Downtrend with pivots should produce short entries."""
        df = _make_downtrend_with_pivots(500)
        s = SwingPivotBreakout()
        sig = s.generate_signal(df)
        assert -1 in sig.values
        short_count = (sig == -1).sum()
        assert short_count > 0
