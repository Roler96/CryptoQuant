"""Tests for ClvAtrMomentum strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_clv_atr_momentum import ClvAtrMomentum


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


def _make_uptrend_df(n: int = 500) -> pd.DataFrame:
    """Create data with CLV oscillations: neutral phases then bullish phases.

    The CLV crosses above 0.3 during bullish phases and below -0.3 during
    neutral/choppy phases, producing real crossover signals.
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)
    open_p = np.zeros(n)
    high = np.zeros(n)
    low = np.zeros(n)
    close = np.zeros(n)

    base = 100.0
    phase = "neutral"  # neutral → bullish → neutral → bullish ...
    phase_bars = 0
    for i in range(n):
        if phase_bars <= 0:
            phase = "bullish" if phase == "neutral" else "neutral"
            phase_bars = 30 + int(rng.integers(0, 20))
        phase_bars -= 1

        bar_range = 0.6 + rng.normal(0, 0.15)
        open_p[i] = base

        if phase == "bullish":
            base += rng.normal(0.1, 0.05)
            low[i] = base - bar_range * 0.2
            close[i] = base + bar_range * 0.5   # close near high
            high[i] = base + bar_range * 0.8
        else:
            base += rng.normal(0, 0.1)
            high[i] = base + bar_range * 0.5
            low[i] = base - bar_range * 0.5
            close[i] = base + rng.normal(0, bar_range * 0.15)  # random close

        base = close[i]

    # Ensure ATR percentile filter fires: add volatility spikes
    for i in range(150, n, 20):
        if i < n:
            bar_range = 2.0 + rng.normal(0, 0.3)
            high[i] = base + bar_range * 0.8
            low[i] = base - bar_range * 0.8
            close[i] = base + bar_range * 0.5
            base = close[i]

    return pd.DataFrame(
        {"open": open_p, "high": high, "low": low, "close": close,
         "volume": np.full(n, 1000.0)},
        index=dates,
    )


def _make_downtrend_df(n: int = 500) -> pd.DataFrame:
    """Create data with CLV oscillations: neutral phases then bearish phases."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)
    open_p = np.zeros(n)
    high = np.zeros(n)
    low = np.zeros(n)
    close = np.zeros(n)

    base = 100.0
    phase = "neutral"
    phase_bars = 0
    for i in range(n):
        if phase_bars <= 0:
            phase = "bearish" if phase == "neutral" else "neutral"
            phase_bars = 30 + int(rng.integers(0, 20))
        phase_bars -= 1

        bar_range = 0.6 + rng.normal(0, 0.15)
        open_p[i] = base

        if phase == "bearish":
            base -= rng.normal(0.1, 0.05)
            high[i] = base + bar_range * 0.8
            close[i] = base - bar_range * 0.5   # close near low
            low[i] = base - bar_range * 0.2
        else:
            base += rng.normal(0, 0.1)
            high[i] = base + bar_range * 0.5
            low[i] = base - bar_range * 0.5
            close[i] = base + rng.normal(0, bar_range * 0.15)

        base = close[i]

    for i in range(150, n, 20):
        if i < n:
            bar_range = 2.0 + rng.normal(0, 0.3)
            high[i] = base + bar_range * 0.8
            low[i] = base - bar_range * 0.8
            close[i] = base - bar_range * 0.5
            base = close[i]

    return pd.DataFrame(
        {"open": open_p, "high": high, "low": low, "close": close,
         "volume": np.full(n, 1000.0)},
        index=dates,
    )


class TestClvAtrMomentum:
    """Tests for the ClvAtrMomentum strategy."""

    def test_default_params_instantiation(self):
        """Strategy can be instantiated with default parameters."""
        s = ClvAtrMomentum()
        assert s.name == "ClvAtrMomentum"
        assert s.timeframe == "1h"
        assert s.min_bars == 120
        assert s.version == "1.0.0"
        assert s.params["clv_period"] == 10
        assert s.params["clv_threshold"] == 0.3
        assert s.params["atr_period"] == 14
        assert s.params["atr_percentile"] == 60
        assert s.params["atr_percentile_window"] == 100

    def test_custom_params_instantiation(self):
        """Strategy can be instantiated with custom parameters."""
        s = ClvAtrMomentum(
            params={"clv_threshold": 0.5, "atr_percentile": 80}
        )
        assert s.params["clv_threshold"] == 0.5
        assert s.params["atr_percentile"] == 80
        assert s.params["clv_period"] == 10

    def test_generate_signal_returns_correct_shape(self):
        """generate_signal() returns Series with correct shape and types."""
        df = _make_flat_df(500)
        s = ClvAtrMomentum()
        signal = s.generate_signal(df)

        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert (signal.index == df.index).all()
        assert signal.dtype == int

    def test_signal_values_valid(self):
        """Signal values are only -1, 0, 1."""
        df = _make_uptrend_df(500)
        s = ClvAtrMomentum()
        signal = s.generate_signal(df)
        unique_vals = set(signal.unique())
        assert unique_vals.issubset({-1, 0, 1})

    def test_insufficient_bars_raises(self):
        """Short DataFrame raises StrategyError via preprocess."""
        df = _make_flat_df(50)
        s = ClvAtrMomentum()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_missing_columns_raises(self):
        """DataFrame missing required columns raises StrategyError."""
        df = pd.DataFrame(
            {"close": [100.0] * 500},
            index=pd.date_range("2024-01-01", periods=500, freq="1h"),
        )
        s = ClvAtrMomentum()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_uptrend_produces_signal(self):
        """Sustained uptrend should produce some non-zero signals."""
        df = _make_uptrend_df(500)
        s = ClvAtrMomentum()
        signal = s.generate_signal(df)
        assert (signal != 0).any()

    def test_downtrend_produces_signal(self):
        """Sustained downtrend should produce some non-zero signals."""
        df = _make_downtrend_df(500)
        s = ClvAtrMomentum()
        signal = s.generate_signal(df)
        assert (signal != 0).any()
