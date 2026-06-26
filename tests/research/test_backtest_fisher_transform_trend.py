"""Tests for FisherTransformTrend strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_fisher_transform_trend import FisherTransformTrend


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


def _make_oscillating_uptrend_df(n: int = 500) -> pd.DataFrame:
    """Create oscillating uptrend data to trigger Fisher crossovers.

    Fisher Transform needs price alternation (up/down swings) to detect
    turning points.  A pure uptrend with monotonic close generates
    few crossovers.  We create oscillation around an upward trend.
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)

    close = np.zeros(n)
    base = 100.0
    for i in range(n):
        # Sawtooth: 30 bars up, 10 bars down, net upward
        if i % 40 < 30:
            base += 0.8
        else:
            base -= 2.0
        noise = rng.normal(0, 0.5)
        close[i] = base + noise

    # Moderate bar range so Fisher peaks are visible
    high = close + np.abs(rng.normal(1.0, 0.5, n))
    low = close - np.abs(rng.normal(1.0, 0.5, n))
    return pd.DataFrame(
        {
            "open": close - 0.5,
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
        noise = rng.normal(0, 0.5)
        close[i] = base + noise

    high = close + np.abs(rng.normal(1.0, 0.5, n))
    low = close - np.abs(rng.normal(1.0, 0.5, n))
    return pd.DataFrame(
        {
            "open": close + 0.5,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


class TestFisherTransformTrend:
    """Tests for the FisherTransformTrend strategy."""

    def test_default_params_instantiation(self):
        """Strategy can be instantiated with default parameters."""
        s = FisherTransformTrend()
        assert s.name == "FisherTransformTrend"
        assert s.timeframe == "1h"
        assert s.min_bars == 210
        assert s.version == "1.0.0"
        assert s.params["fisher_period"] == 10
        assert s.params["signal_period"] == 5
        assert s.params["trend_period"] == 200

    def test_custom_params_instantiation(self):
        """Strategy can be instantiated with custom parameters."""
        s = FisherTransformTrend(
            params={"fisher_period": 15, "signal_period": 8, "trend_period": 100}
        )
        assert s.params["fisher_period"] == 15
        assert s.params["signal_period"] == 8
        assert s.params["trend_period"] == 100

    def test_generate_signal_returns_correct_shape(self):
        """generate_signal() returns Series with correct shape and types."""
        df = _make_flat_df(500)
        s = FisherTransformTrend()
        signal = s.generate_signal(df)

        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert (signal.index == df.index).all()
        assert signal.dtype == int

    def test_signal_values_valid(self):
        """Signal values are only -1, 0, 1."""
        df = _make_oscillating_uptrend_df(500)
        s = FisherTransformTrend()
        signal = s.generate_signal(df)
        unique_vals = set(signal.unique())
        assert unique_vals.issubset({-1, 0, 1})

    def test_insufficient_bars_raises(self):
        """Short DataFrame raises StrategyError via preprocess."""
        df = _make_flat_df(150)
        s = FisherTransformTrend()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_missing_columns_raises(self):
        """DataFrame missing required columns raises StrategyError."""
        df = pd.DataFrame(
            {"close": [100.0] * 500},
            index=pd.date_range("2024-01-01", periods=500, freq="1h"),
        )
        s = FisherTransformTrend()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_uptrend_produces_long_signals(self):
        """Oscillating uptrend data should produce long signals."""
        df = _make_oscillating_uptrend_df(500)
        s = FisherTransformTrend()
        signal = s.generate_signal(df)
        assert (signal == 1).any()

    def test_downtrend_produces_short_signals(self):
        """Oscillating downtrend data should produce short signals."""
        df = _make_oscillating_downtrend_df(500)
        s = FisherTransformTrend()
        signal = s.generate_signal(df)
        assert (signal == -1).any()
