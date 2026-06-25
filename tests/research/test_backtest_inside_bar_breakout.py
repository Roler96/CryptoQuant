"""Tests for InsideBarBreakout strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_inside_bar_breakout import InsideBarBreakout


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


def _make_breakout_df(n: int = 500) -> pd.DataFrame:
    """Create data with alternating compression-then-expansion breakouts.

    Pattern: 20 normal bars (small range ~0.5), then 1 inside bar (compression,
    range ~0.2), then 1 expansion bar (range ~3.0 = 6× normal). The expansion
    bar range >> ATR × 1.5, so the expansion filter passes.
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)
    close = np.zeros(n)
    high = np.zeros(n)
    low = np.zeros(n)

    base = 100.0
    i = 0
    while i < n:
        # 20 normal bars
        for _ in range(20):
            if i >= n:
                break
            bar_range = 0.5 + rng.normal(0, 0.1)
            close[i] = base + rng.normal(0, bar_range * 0.2)
            high[i] = max(close[i] + bar_range * 0.3, base + bar_range * 0.3)
            low[i] = min(close[i] - bar_range * 0.3, base - bar_range * 0.3)
            base = close[i]
            i += 1
        if i >= n:
            break
        # 1 inside bar (compression)
        if i < n:
            high[i] = base + 0.2
            low[i] = base - 0.2
            close[i] = base
            i += 1
        # 1 expansion bar (breakout up)
        if i < n:
            base += 2.0
            close[i] = base
            high[i] = base + 3.0  # range ~3.5, much larger than normal 0.5
            low[i] = base - 0.5
            i += 1

    volume = np.full(n, 1000.0)
    return pd.DataFrame(
        {"open": close - 0.1, "high": high, "low": low,
         "close": close, "volume": volume},
        index=dates,
    )


def _make_downtrend_breakout_df(n: int = 500) -> pd.DataFrame:
    """Create data with alternating compression-then-expansion breakdowns.

    Same pattern as _make_breakout_df but with downside breakouts.
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)
    close = np.zeros(n)
    high = np.zeros(n)
    low = np.zeros(n)

    base = 100.0
    i = 0
    while i < n:
        for _ in range(20):
            if i >= n:
                break
            bar_range = 0.5 + rng.normal(0, 0.1)
            close[i] = base + rng.normal(0, bar_range * 0.2)
            high[i] = max(close[i] + bar_range * 0.3, base + bar_range * 0.3)
            low[i] = min(close[i] - bar_range * 0.3, base - bar_range * 0.3)
            base = close[i]
            i += 1
        if i >= n:
            break
        if i < n:
            high[i] = base + 0.2
            low[i] = base - 0.2
            close[i] = base
            i += 1
        if i < n:
            base -= 2.0
            close[i] = base
            high[i] = base + 0.5
            low[i] = base - 3.0  # range ~3.5 expansion
            i += 1

    volume = np.full(n, 1000.0)
    return pd.DataFrame(
        {"open": close - 0.1, "high": high, "low": low,
         "close": close, "volume": volume},
        index=dates,
    )


class TestInsideBarBreakout:
    """Tests for the InsideBarBreakout strategy."""

    def test_default_params_instantiation(self):
        """Strategy can be instantiated with default parameters."""
        s = InsideBarBreakout()
        assert s.name == "InsideBarBreakout"
        assert s.timeframe == "1h"
        assert s.min_bars == 60
        assert s.version == "1.0.0"
        assert s.params["atr_period"] == 14
        assert s.params["expansion_mult"] == 1.5

    def test_custom_params_instantiation(self):
        """Strategy can be instantiated with custom parameters."""
        s = InsideBarBreakout(
            params={"atr_period": 20, "expansion_mult": 2.0}
        )
        assert s.params["atr_period"] == 20
        assert s.params["expansion_mult"] == 2.0

    def test_generate_signal_returns_correct_shape(self):
        """generate_signal() returns Series with correct shape and types."""
        df = _make_flat_df(500)
        s = InsideBarBreakout()
        signal = s.generate_signal(df)

        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert (signal.index == df.index).all()
        assert signal.dtype == int

    def test_signal_values_valid(self):
        """Signal values are only -1, 0, 1."""
        df = _make_breakout_df(500)
        s = InsideBarBreakout()
        signal = s.generate_signal(df)
        unique_vals = set(signal.unique())
        assert unique_vals.issubset({-1, 0, 1})

    def test_insufficient_bars_raises(self):
        """Short DataFrame raises StrategyError via preprocess."""
        df = _make_flat_df(30)
        s = InsideBarBreakout()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_missing_columns_raises(self):
        """DataFrame missing required columns raises StrategyError."""
        df = pd.DataFrame(
            {"close": [100.0] * 500},
            index=pd.date_range("2024-01-01", periods=500, freq="1h"),
        )
        s = InsideBarBreakout()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_breakout_produces_signal(self):
        """Data with expansion breakouts should produce signals."""
        df = _make_breakout_df(500)
        s = InsideBarBreakout()
        signal = s.generate_signal(df)
        assert (signal != 0).any()

    def test_downtrend_breakout_produces_signal(self):
        """Data with expansion breakdowns should produce signals."""
        df = _make_downtrend_breakout_df(500)
        s = InsideBarBreakout()
        signal = s.generate_signal(df)
        assert (signal != 0).any()
