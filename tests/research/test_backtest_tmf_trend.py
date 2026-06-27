"""Tests for TMFTrend strategy."""

import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError


# ── Test data ─────────────────────────────────────────────────────


def _make_df(n: int = 500, volatility: str = "high") -> pd.DataFrame:
    """Synthetic OHLCV with expanding volatility."""
    rng = np.random.default_rng(42)
    if volatility == "high":
        noise_scale = np.linspace(0.5, 3.0, n)
    else:
        noise_scale = np.ones(n) * 0.3

    base = np.linspace(90, 110, n) + rng.normal(0, 1, n)
    idx = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    idx = idx.tz_localize(None)
    return pd.DataFrame(
        {
            "open": base + rng.normal(0, 0.3, n),
            "high": base + np.abs(rng.normal(1, 1.0, n)) * noise_scale,
            "low": base - np.abs(rng.normal(1, 1.0, n)) * noise_scale,
            "close": base,
            "volume": rng.uniform(100, 1000, n),
        },
        index=idx,
    )


def _make_trending_df(n: int = 500, direction: str = "up") -> pd.DataFrame:
    """Strong trending data with bar-level direction for TMF (needs close ≠ open)."""
    rng = np.random.default_rng(42)
    idx = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    idx = idx.tz_localize(None)

    if direction == "up":
        # Bullish bars: open below close with noise, trending up
        open_ = np.linspace(90, 128, n) + rng.normal(0, 1.5, n)
        close = open_ + np.abs(rng.normal(1.5, 1.0, n))  # close above open
    else:
        # Bearish bars: open above close with noise, trending down
        open_ = np.linspace(130, 92, n) + rng.normal(0, 1.5, n)
        close = open_ - np.abs(rng.normal(1.5, 1.0, n))  # close below open

    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + np.abs(rng.normal(2, 1.5, n)),
            "low": np.minimum(open_, close) - np.abs(rng.normal(1.5, 1, n)),
            "close": close,
            "volume": rng.uniform(100, 1000, n),
        },
        index=idx,
    )


# ── Strategy tests ────────────────────────────────────────────────


class TestTMFTrend:
    """Tests for the TMFTrend strategy class."""

    def test_import(self):
        """Strategy module imports without error."""
        from research.backtest_tmf_trend import TMFTrend
        assert TMFTrend is not None

    def test_generate_signal_shape(self):
        """generate_signal() returns Series with same length and index."""
        from research.backtest_tmf_trend import TMFTrend

        df = _make_df(300, "high")
        strategy = TMFTrend()
        signals = strategy.generate_signal(df)
        assert isinstance(signals, pd.Series)
        assert len(signals) == len(df)
        assert signals.index.equals(df.index)

    def test_insufficient_bars_raises(self):
        """Raises StrategyError when len(df) < min_bars."""
        from research.backtest_tmf_trend import TMFTrend

        df = _make_df(50, "high")
        strategy = TMFTrend()
        with pytest.raises(StrategyError):
            strategy.generate_signal(df)

    def test_signals_on_trending_data(self):
        """Strategy generates non-zero signals on strong trending data."""
        from research.backtest_tmf_trend import TMFTrend

        df = _make_trending_df(500, "up")
        strategy = TMFTrend()
        signals = strategy.generate_signal(df)

        nonzero = (signals != 0).sum()
        assert nonzero > 0, f"Expected non-zero signals, got all flat ({len(signals)} bars)"

    def test_signal_values_are_valid(self):
        """Signals only contain -1, 0, or 1."""
        from research.backtest_tmf_trend import TMFTrend

        df = _make_df(300, "high")
        strategy = TMFTrend()
        signals = strategy.generate_signal(df)
        unique = set(signals.unique())
        assert unique <= {-1, 0, 1}, f"Unexpected signal values: {unique}"
