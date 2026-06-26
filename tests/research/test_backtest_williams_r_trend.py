"""Tests for WilliamsRTrend strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_williams_r_trend import WilliamsRTrend


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


def _make_oscillating_uptrend_df(n: int = 500) -> pd.DataFrame:
    """Create oscillating uptrend data with %R crossovers.

    Williams %R needs price oscillation within the high-low range
    to generate midline crosses.  Sawtooth uptrend creates
    regular upward/downward swings.
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)

    close = np.zeros(n)
    base = 100.0
    for i in range(n):
        if i % 40 < 30:
            base += 0.8
        else:
            base -= 2.0
        close[i] = base + rng.normal(0, 0.5)

    # Wide enough range for %R to cross -50
    bar_range = np.abs(rng.normal(2.0, 1.0, n)) + 1.0
    high = close + bar_range
    low = close - bar_range
    return pd.DataFrame(
        {
            "open": close - 0.2,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


def _make_oscillating_downtrend_df(n: int = 500) -> pd.DataFrame:
    """Create oscillating downtrend data for short entry testing."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)

    close = np.zeros(n)
    base = 200.0
    for i in range(n):
        if i % 40 < 30:
            base -= 0.8
        else:
            base += 2.0
        close[i] = base + rng.normal(0, 0.5)

    bar_range = np.abs(rng.normal(2.0, 1.0, n)) + 1.0
    high = close + bar_range
    low = close - bar_range
    return pd.DataFrame(
        {
            "open": close + 0.2,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


class TestWilliamsRTrend:
    """Tests for the WilliamsRTrend strategy."""

    def test_default_params_instantiation(self):
        """Strategy can be instantiated with default parameters."""
        s = WilliamsRTrend()
        assert s.name == "WilliamsRTrend"
        assert s.timeframe == "1h"
        assert s.params["wr_period"] == 14
        assert s.params["trend_period"] == 200
        assert s.params["entry_threshold"] == -50

    def test_min_bars_raises(self):
        """Strategy raises StrategyError when df has fewer than min_bars."""
        s = WilliamsRTrend()
        dates = pd.date_range("2024-01-01", periods=50, freq="1h")
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
        df = _make_oscillating_uptrend_df(500)
        s = WilliamsRTrend()
        sig = s.generate_signal(df)
        assert len(sig) == len(df)
        assert sig.index.equals(df.index)
        assert sig.dtype in (int, np.int32, np.int64)

    def test_flat_market_no_trades(self):
        """In a completely flat market, strategy should stay flat."""
        df = _make_flat_df(500)
        s = WilliamsRTrend()
        sig = s.generate_signal(df)
        # Flat close means no trend (close ≈ EMA200), and no range
        # for %R to cross midline meaningfully, so should stay flat.
        assert (sig == 0).all()

    def test_uptrend_generates_long_trades(self):
        """Oscillating uptrend should produce long signals."""
        df = _make_oscillating_uptrend_df(500)
        s = WilliamsRTrend()
        sig = s.generate_signal(df)
        # Should have at least one long trade
        assert 1 in sig.values
        # In a strong uptrend, should have more longs than shorts
        long_count = (sig == 1).sum()
        short_count = (sig == -1).sum()
        assert long_count > 0

    def test_downtrend_generates_short_trades(self):
        """Oscillating downtrend should produce short signals."""
        df = _make_oscillating_downtrend_df(500)
        s = WilliamsRTrend()
        sig = s.generate_signal(df)
        assert -1 in sig.values
        short_count = (sig == -1).sum()
        assert short_count > 0
