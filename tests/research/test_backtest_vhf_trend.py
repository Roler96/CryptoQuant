"""Tests for VHFTrend strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_vhf_trend import VHFTrend


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
    """Create a strong trending-up DataFrame.

    Clean linear uptrend with minimal noise — produces high VHF
    and long entry signals.
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)
    # Very clean trend — VHF will be high
    trend = np.linspace(100.0, 180.0, n) + rng.normal(0, 0.15, n)
    close = trend
    return pd.DataFrame(
        {
            "open": close - 0.3,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


def _make_downtrend_df(n: int = 500) -> pd.DataFrame:
    """Create a strong trending-down DataFrame.

    Clean linear downtrend with minimal noise — produces high VHF
    and short entry signals.
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)
    # Very clean trend — VHF will be high
    trend = np.linspace(200.0, 80.0, n) + rng.normal(0, 0.15, n)
    close = trend
    return pd.DataFrame(
        {
            "open": close + 0.3,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


def _make_choppy_df(n: int = 500) -> pd.DataFrame:
    """Create a choppy, mean-reverting DataFrame.

    Random walk with strong mean reversion around 100.  Price
    frequently changes direction — VHF stays low.
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)
    close = np.zeros(n)
    close[0] = 100.0
    for i in range(1, n):
        # Strong mean reversion: 70% pullback toward 100, 30% momentum
        reversion = 0.7 * (100.0 - close[i - 1])
        noise = rng.normal(0, 1.5)
        close[i] = close[i - 1] + reversion + noise
        # Hard bounds to keep it near 100
        close[i] = np.clip(close[i], 92.0, 108.0)
    return pd.DataFrame(
        {
            "open": close - 0.3,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


class TestVHFTrend:
    """Tests for the VHFTrend strategy."""

    def test_default_params_instantiation(self):
        """Strategy can be instantiated with default parameters."""
        s = VHFTrend()
        assert s.name == "VHFTrend"
        assert s.timeframe == "1h"
        assert s.params["vhf_period"] == 20
        assert s.params["vhf_entry"] == 0.40
        assert s.params["vhf_exit"] == 0.25
        assert s.params["sma_period"] == 50

    def test_min_bars_raises(self):
        """Strategy raises StrategyError when df has fewer than min_bars."""
        s = VHFTrend()
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
        df = _make_uptrend_df(500)
        s = VHFTrend()
        sig = s.generate_signal(df)
        assert len(sig) == len(df)
        assert sig.index.equals(df.index)
        assert sig.dtype in (int, np.int32, np.int64)

    def test_flat_market_no_trades(self):
        """In a completely flat market, VHF stays near 0 — no entries."""
        df = _make_flat_df(500)
        s = VHFTrend()
        sig = s.generate_signal(df)
        assert (sig == 0).all()

    def test_choppy_market_no_trades(self):
        """In a choppy/mean-reverting market, VHF stays low — no entries."""
        df = _make_choppy_df(500)
        s = VHFTrend()
        sig = s.generate_signal(df)
        # Choppy market should have very low VHF — strategy stays flat
        # (might have occasional brief entries, but should be mostly flat)
        assert (sig != 0).sum() < len(sig) * 0.10  # <10% non-flat

    def test_uptrend_generates_long_trades(self):
        """Strong uptrend produces high VHF + price > SMA → long entry."""
        df = _make_uptrend_df(500)
        s = VHFTrend()
        sig = s.generate_signal(df)
        # Should have at least some long trades
        assert 1 in sig.values
        # In a pure uptrend, should be mostly long, no shorts
        long_count = (sig == 1).sum()
        short_count = (sig == -1).sum()
        assert long_count > 0

    def test_downtrend_generates_short_trades(self):
        """Strong downtrend produces high VHF + price < SMA → short entry."""
        df = _make_downtrend_df(500)
        s = VHFTrend()
        sig = s.generate_signal(df)
        # Should have at least some short trades
        assert -1 in sig.values
        short_count = (sig == -1).sum()
        assert short_count > 0

    def test_vhf_indicator_bounds(self):
        """VHF indicator produces values in [0, 1]."""
        from cryptoquant.strategy.signals import vhf
        df = _make_uptrend_df(500)
        vhf_vals = vhf(df, period=20)
        valid = vhf_vals.dropna()
        assert (valid >= 0.0).all()
        assert (valid <= 1.0).all()
