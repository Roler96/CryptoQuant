"""Tests for AroonTrendContinuation strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_aroon_trend_continuation import AroonTrendContinuation


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


def _make_aroon_uptrend_df(n: int = 500) -> pd.DataFrame:
    """Create data that triggers Aroon Up > 70 long entries.

    Pattern: steady uptrend with new highs every few bars, so Aroon Up
    stays high. Price well above EMA50.

    Strategy: after a consolidation period (aroon low), push price up
    making new highs rapidly — this pushes Aroon Up > 70.
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)

    close = np.zeros(n)
    high = np.zeros(n)
    low = np.zeros(n)
    base = 110.0  # above EMA50 starting from ~100

    i = 0
    while i < n:
        # 5 bars consolidation near base
        for _ in range(5):
            if i >= n:
                break
            noise = rng.normal(0, 0.1)
            close[i] = base + noise
            high[i] = close[i] + abs(rng.normal(0, 0.2))
            low[i] = close[i] - abs(rng.normal(0, 0.2))
            i += 1
        # 5 bars making new highs (pushes Aroon Up > 70)
        for step in range(5):
            if i >= n:
                break
            base += 0.5 + step * 0.2  # accelerating trend
            noise = rng.normal(0, 0.05)
            close[i] = base + noise
            high[i] = close[i] + 0.3
            low[i] = close[i] - 0.3
            i += 1

    volume = np.full(n, 1000.0)
    return pd.DataFrame(
        {"open": close - 0.1, "high": high, "low": low,
         "close": close, "volume": volume},
        index=dates,
    )


def _make_aroon_downtrend_df(n: int = 500) -> pd.DataFrame:
    """Create data that triggers Aroon Down > 70 short entries.

    Pattern: steady downtrend below EMA50 with new lows every few bars.
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)

    close = np.zeros(n)
    high = np.zeros(n)
    low = np.zeros(n)
    base = 90.0  # below EMA50 starting from ~100

    i = 0
    while i < n:
        # 5 bars consolidation near base
        for _ in range(5):
            if i >= n:
                break
            noise = rng.normal(0, 0.1)
            close[i] = base + noise
            high[i] = close[i] + abs(rng.normal(0, 0.2))
            low[i] = close[i] - abs(rng.normal(0, 0.2))
            i += 1
        # 5 bars making new lows (pushes Aroon Down > 70)
        for step in range(5):
            if i >= n:
                break
            base -= 0.5 + step * 0.2  # accelerating downtrend
            noise = rng.normal(0, 0.05)
            close[i] = base + noise
            high[i] = close[i] + 0.3
            low[i] = close[i] - 0.3
            i += 1

    volume = np.full(n, 1000.0)
    return pd.DataFrame(
        {"open": close - 0.1, "high": high, "low": low,
         "close": close, "volume": volume},
        index=dates,
    )


class TestAroonTrendContinuation:
    """Tests for the AroonTrendContinuation strategy."""

    def test_default_params_instantiation(self):
        """Strategy can be instantiated with default parameters."""
        s = AroonTrendContinuation()
        assert s.name == "AroonTrendContinuation"
        assert s.timeframe == "1h"
        assert s.min_bars == 80
        assert s.version == "1.0.0"
        assert s.params["aroon_period"] == 25
        assert s.params["aroon_threshold"] == 70
        assert s.params["aroon_exit"] == 50
        assert s.params["trend_period"] == 50

    def test_custom_params_instantiation(self):
        """Strategy can be instantiated with custom parameters."""
        s = AroonTrendContinuation(
            params={
                "aroon_period": 14,
                "aroon_threshold": 80,
                "aroon_exit": 40,
                "trend_period": 100,
            }
        )
        assert s.params["aroon_period"] == 14
        assert s.params["aroon_threshold"] == 80
        assert s.params["aroon_exit"] == 40
        assert s.params["trend_period"] == 100

    def test_generate_signal_returns_correct_shape(self):
        """generate_signal() returns Series with correct shape and types."""
        df = _make_flat_df(500)
        s = AroonTrendContinuation()
        signal = s.generate_signal(df)

        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert (signal.index == df.index).all()
        assert signal.dtype == int

    def test_signal_values_valid(self):
        """Signal values are only -1, 0, 1."""
        df = _make_aroon_uptrend_df(500)
        s = AroonTrendContinuation()
        signal = s.generate_signal(df)
        unique_vals = set(signal.unique())
        assert unique_vals.issubset({-1, 0, 1})

    def test_insufficient_bars_raises(self):
        """Short DataFrame raises StrategyError via preprocess."""
        df = _make_flat_df(50)
        s = AroonTrendContinuation()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_missing_columns_raises(self):
        """DataFrame missing required columns raises StrategyError."""
        df = pd.DataFrame(
            {"close": [100.0] * 500},
            index=pd.date_range("2024-01-01", periods=500, freq="1h"),
        )
        s = AroonTrendContinuation()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_uptrend_produces_long_signals(self):
        """Uptrend with new highs should produce long signals."""
        df = _make_aroon_uptrend_df(500)
        s = AroonTrendContinuation()
        signal = s.generate_signal(df)
        assert (signal == 1).any()

    def test_downtrend_produces_short_signals(self):
        """Downtrend with new lows should produce short signals."""
        df = _make_aroon_downtrend_df(500)
        s = AroonTrendContinuation()
        signal = s.generate_signal(df)
        assert (signal == -1).any()
