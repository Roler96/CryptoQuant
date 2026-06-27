"""Tests for RmiTrend strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_rmi_trend import RmiTrend


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
    """Create a clean trending-up DataFrame for RMI testing."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)
    trend = np.linspace(100.0, 200.0, n)
    noise = rng.normal(0, 1.5, n)
    close = trend + noise
    return pd.DataFrame(
        {
            "open": close - 0.5,
            "high": close + 1.5,
            "low": close - 1.5,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


def _make_downtrend_df(n: int = 500) -> pd.DataFrame:
    """Create a clean trending-down DataFrame for RMI testing."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)
    trend = np.linspace(200.0, 80.0, n)
    noise = rng.normal(0, 1.5, n)
    close = trend + noise
    return pd.DataFrame(
        {
            "open": close + 0.5,
            "high": close + 1.5,
            "low": close - 1.5,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


def _make_choppy_df(n: int = 500) -> pd.DataFrame:
    """Create a choppy, mean-reverting DataFrame."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)
    close = np.zeros(n)
    close[0] = 100.0
    for i in range(1, n):
        reversion = 0.7 * (100.0 - close[i - 1])
        noise = rng.normal(0, 1.5)
        close[i] = close[i - 1] + reversion + noise
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


class TestRmiTrend:
    """Tests for the RmiTrend strategy."""

    def test_default_params_instantiation(self):
        """Strategy can be instantiated with default parameters."""
        s = RmiTrend()
        assert s.name == "RmiTrend"
        assert s.timeframe == "1h"
        assert s.params["momentum_period"] == 5
        assert s.params["rmi_period"] == 14
        assert s.params["signal_period"] == 9
        assert s.params["trend_period"] == 200

    def test_min_bars_raises(self):
        """Strategy raises StrategyError when df has fewer than min_bars."""
        s = RmiTrend()
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
        s = RmiTrend()
        sig = s.generate_signal(df)
        assert len(sig) == len(df)
        assert sig.index.equals(df.index)
        assert sig.dtype in (int, np.int32, np.int64)

    def test_flat_market_no_trades(self):
        """In a completely flat market, RMI stays near 50 — minimal signals."""
        df = _make_flat_df(500)
        s = RmiTrend()
        sig = s.generate_signal(df)
        # Flat market = zero momentum = RMI stays near 50 = no crossovers
        assert (sig != 0).sum() < len(sig) * 0.10  # <10% non-flat

    def test_uptrend_generates_long_trades(self):
        """Strong uptrend produces positive momentum → RMI rises → long entry."""
        df = _make_uptrend_df(500)
        s = RmiTrend()
        sig = s.generate_signal(df)
        assert 1 in sig.values
        long_count = (sig == 1).sum()
        assert long_count > 0

    def test_downtrend_generates_short_trades(self):
        """Strong downtrend produces negative momentum → RMI falls → short."""
        df = _make_downtrend_df(500)
        s = RmiTrend()
        sig = s.generate_signal(df)
        assert -1 in sig.values
        short_count = (sig == -1).sum()
        assert short_count > 0

    def test_rmi_indicator_bounds(self):
        """RMI indicator produces values in [0, 100]."""
        from cryptoquant.strategy.signals import rmi
        df = _make_uptrend_df(500)
        rmi_df = rmi(df)
        rmi_vals = rmi_df["rmi"].dropna()
        assert (rmi_vals >= 0.0).all()
        assert (rmi_vals <= 100.0).all()
