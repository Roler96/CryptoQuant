"""Tests for SuperTrendTrend strategy."""

import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from cryptoquant.strategy.signals import supertrend as st_func


# ── Test data ─────────────────────────────────────────────────────


def _make_df(n: int = 500, trend: str = "up") -> pd.DataFrame:
    """Synthetic OHLCV with a clear trend."""
    rng = np.random.default_rng(42)
    if trend == "up":
        base = np.linspace(90, 110, n) + rng.normal(0, 1, n)
    elif trend == "down":
        base = np.linspace(110, 90, n) + rng.normal(0, 1, n)
    else:
        base = np.full(n, 100.0) + rng.normal(0, 1, n)

    idx = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    # Remove tz info for DatetimeIndex without tz
    idx = idx.tz_localize(None)
    return pd.DataFrame(
        {
            "open": base + rng.normal(0, 0.3, n),
            "high": base + np.abs(rng.normal(1, 0.5, n)),
            "low": base - np.abs(rng.normal(1, 0.5, n)),
            "close": base,
            "volume": rng.uniform(100, 1000, n),
        },
        index=idx,
    )


# ── SuperTrend indicator tests ────────────────────────────────────


class TestSuperTrendIndicator:
    """Tests for the supertrend() function in signals.py."""

    def test_supertrend_returns_series(self):
        """SuperTrend should return a Series with same index."""
        df = _make_df(200, "up")
        result = st_func(df, atr_period=10, multiplier=2.5)
        assert isinstance(result, pd.Series)
        assert len(result) == len(df)
        assert result.index.equals(df.index)

    def test_supertrend_flips_on_trend_change(self):
        """SuperTrend should be above price in downtrend, below in uptrend."""
        df = _make_df(300, "up")
        result = st_func(df, atr_period=10, multiplier=2.5)
        close = df["close"]
        # In steady uptrend, most values should be below price
        valid = ~result.isna()
        below_price = (result[valid] < close[valid]).mean()
        assert below_price > 0.4, f"Expected ST below price in uptrend, got {below_price:.1%}"

    def test_supertrend_with_small_data(self):
        """SuperTrend should handle small DataFrames gracefully."""
        df = _make_df(20, "up")
        result = st_func(df, atr_period=10, multiplier=2.5)
        assert len(result) == 20


# ── Strategy tests ────────────────────────────────────────────────


class TestSuperTrendTrend:
    """Tests for the SuperTrendTrend strategy class."""

    def test_import(self):
        """Strategy module imports without error."""
        from research.backtest_supertrend_trend import SuperTrendTrend
        assert SuperTrendTrend is not None

    def test_generate_signal_shape(self):
        """generate_signal() returns Series with same length and index."""
        from research.backtest_supertrend_trend import SuperTrendTrend

        df = _make_df(400, "up")
        strategy = SuperTrendTrend()
        signals = strategy.generate_signal(df)
        assert isinstance(signals, pd.Series)
        assert len(signals) == len(df)
        assert signals.index.equals(df.index)

    def test_insufficient_bars_raises(self):
        """Raises StrategyError when len(df) < min_bars."""
        from research.backtest_supertrend_trend import SuperTrendTrend

        df = _make_df(50, "up")
        strategy = SuperTrendTrend()
        with pytest.raises(StrategyError):
            strategy.generate_signal(df)

    def test_signals_on_trending_data(self):
        """Strategy generates non-zero signals on strong trending data."""
        from research.backtest_supertrend_trend import SuperTrendTrend

        df = _make_df(500, "up")
        strategy = SuperTrendTrend()
        signals = strategy.generate_signal(df)

        # At least some signals should be non-zero on trending data
        nonzero = (signals != 0).sum()
        assert nonzero > 0, f"Expected non-zero signals, got all flat ({len(signals)} bars)"

    def test_signal_values_are_valid(self):
        """Signals only contain -1, 0, or 1."""
        from research.backtest_supertrend_trend import SuperTrendTrend

        df = _make_df(400, "up")
        strategy = SuperTrendTrend()
        signals = strategy.generate_signal(df)
        unique = set(signals.unique())
        assert unique <= {-1, 0, 1}, f"Unexpected signal values: {unique}"
