"""Tests for CCITrend strategy."""

import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError


# ── Test data ─────────────────────────────────────────────────────


def _make_df(n: int = 500) -> pd.DataFrame:
    """Synthetic OHLCV with a gentle uptrend and some volatility."""
    rng = np.random.default_rng(42)
    base = np.linspace(90, 120, n) + rng.normal(0, 1.5, n)
    idx = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    idx = idx.tz_localize(None)
    return pd.DataFrame(
        {
            "open": base + rng.normal(0, 0.5, n),
            "high": base + np.abs(rng.normal(1.5, 1.0, n)),
            "low": base - np.abs(rng.normal(1.5, 1.0, n)),
            "close": base,
            "volume": rng.uniform(100, 1000, n),
        },
        index=idx,
    )


def _make_trending_df(n: int = 500, direction: str = "up") -> pd.DataFrame:
    """Strong trending data for signal generation."""
    rng = np.random.default_rng(42)
    if direction == "up":
        base = np.linspace(90, 150, n) + rng.normal(0, 2, n)
    else:
        base = np.linspace(150, 90, n) + rng.normal(0, 2, n)

    idx = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    idx = idx.tz_localize(None)
    return pd.DataFrame(
        {
            "open": base,
            "high": base + np.abs(rng.normal(2, 1.5, n)),
            "low": base - np.abs(rng.normal(1.5, 1.0, n)),
            "close": base,
            "volume": rng.uniform(100, 1000, n),
        },
        index=idx,
    )


# ── Strategy tests ────────────────────────────────────────────────


class TestCCITrend:
    """Tests for the CCITrend strategy class."""

    def test_import(self):
        """Strategy module imports without error."""
        from research.backtest_cci_trend import CCITrend
        assert CCITrend is not None

    def test_generate_signal_shape(self):
        """generate_signal() returns Series with same length and index."""
        from research.backtest_cci_trend import CCITrend

        df = _make_df(300)
        strategy = CCITrend()
        signals = strategy.generate_signal(df)
        assert isinstance(signals, pd.Series)
        assert len(signals) == len(df)
        assert signals.index.equals(df.index)

    def test_insufficient_bars_raises(self):
        """Raises StrategyError when len(df) < min_bars."""
        from research.backtest_cci_trend import CCITrend

        df = _make_df(50)
        strategy = CCITrend()
        with pytest.raises(StrategyError):
            strategy.generate_signal(df)

    def test_signals_on_trending_data(self):
        """Strategy generates non-zero signals on strong trending data."""
        from research.backtest_cci_trend import CCITrend

        df = _make_trending_df(500, "up")
        strategy = CCITrend()
        signals = strategy.generate_signal(df)

        nonzero = (signals != 0).sum()
        assert nonzero > 0, f"Expected non-zero signals, got all flat ({len(signals)} bars)"

    def test_signal_values_are_valid(self):
        """Signals only contain -1, 0, or 1."""
        from research.backtest_cci_trend import CCITrend

        df = _make_df(300)
        strategy = CCITrend()
        signals = strategy.generate_signal(df)
        unique = set(signals.unique())
        assert unique <= {-1, 0, 1}, f"Unexpected signal values: {unique}"
