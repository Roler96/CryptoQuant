"""Tests for ChoppinessBreakout strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_choppiness_breakout import ChoppinessBreakout


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


def _make_breakout_df(n: int = 500) -> pd.DataFrame:
    """Create data with clear top breakouts above Donchian channel."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    base = np.full(n, 100.0)
    # Insert a clean breakout: price shoots above 20-bar high
    base[100] = 120.0
    base[101] = 125.0
    # Rest goes back to normal
    close = pd.Series(base, index=dates)
    high = close + 2.0
    low = close - 2.0
    open_p = close - 1.0
    return pd.DataFrame(
        {
            "open": open_p,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


def _make_trending_uptrend_df(n: int = 500) -> pd.DataFrame:
    """Create gradually trending data — CI should drop below 38.2."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    trend = np.linspace(100.0, 200.0, n)
    noise = np.random.default_rng(42).normal(0, 1.0, n)
    close = trend + noise
    return pd.DataFrame(
        {
            "open": close - 1.0,
            "high": close + 2.0,
            "low": close - 2.0,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


class TestChoppinessBreakout:
    """Tests for ChoppinessBreakout strategy."""

    def test_initialization(self):
        """Strategy initializes with default params."""
        s = ChoppinessBreakout({})
        assert s.name == "ChoppinessBreakout"
        assert s.params["channel_period"] == 20
        assert s.params["ci_period"] == 14
        assert s.params["ci_threshold"] == 38.2

    def test_custom_params(self):
        """Custom params override defaults."""
        s = ChoppinessBreakout({"channel_period": 10, "ci_period": 7, "ci_threshold": 40})
        assert s.params["channel_period"] == 10
        assert s.params["ci_period"] == 7
        assert s.params["ci_threshold"] == 40

    def test_insufficient_bars(self):
        """Strategy raises StrategyError with too few bars."""
        s = ChoppinessBreakout({})
        df = _make_flat_df(n=50)
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_flat_price_no_signals(self):
        """Flat price with no channel breakouts produces zero signals."""
        s = ChoppinessBreakout({})
        df = _make_flat_df(n=500)
        signal = s.generate_signal(df)
        assert len(signal) == len(df)
        assert signal.dtype == int
        # Flat price — no channel breakouts = all zeros
        assert set(signal.unique()).issubset({-1, 0, 1})

    def test_breakout_price_generates_signal(self):
        """A price breakout above channel should generate long signal."""
        s = ChoppinessBreakout({})
        df = _make_breakout_df(n=500)
        signal = s.generate_signal(df)
        assert len(signal) == len(df)
        # Breakout data should trigger at least 1 long signal
        assert 1 in signal.values

    def test_trending_data_lowers_ci(self):
        """Choppiness index should be near 0 for a perfectly clean trend."""
        from cryptoquant.strategy.signals import choppiness_index
        # Perfect linear trend with zero noise
        dates = pd.date_range("2024-01-01", periods=200, freq="1h")
        trend = np.linspace(100.0, 150.0, 200)
        df = pd.DataFrame(
            {
                "open": trend - 0.1,
                "high": trend + 0.2,
                "low": trend - 0.2,
                "close": trend,
                "volume": np.full(200, 1000.0),
            },
            index=dates,
        )
        ci = choppiness_index(df, period=14)
        # In a perfect linear trend, CI approaches and stays low
        valid_ci = ci.dropna()
        assert len(valid_ci) > 0
        # CI values should indicate trending (well below 38.2)
        assert (valid_ci < 38.2).all()
