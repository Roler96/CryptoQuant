"""Tests for EfficiencyRatioTrend strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_efficiency_ratio_trend import EfficiencyRatioTrend


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


def _make_strong_uptrend_df(n: int = 500) -> pd.DataFrame:
    """Create strong uptrend data — high ER values expected.

    ER measures directional efficiency: a clean trend produces
    ER close to 1.0.  We create a steady climb with low noise.
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)

    close = np.zeros(n)
    base = 100.0
    for i in range(n):
        base += 0.20  # steady climb with low noise
        noise = rng.normal(0, 0.3)
        close[i] = base + noise

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


def _make_strong_downtrend_df(n: int = 500) -> pd.DataFrame:
    """Create strong downtrend data for short entry testing."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)

    close = np.zeros(n)
    base = 200.0
    for i in range(n):
        base -= 0.20
        noise = rng.normal(0, 0.3)
        close[i] = base + noise

    high = close + 0.5
    low = close - 0.5
    return pd.DataFrame(
        {
            "open": close + 0.1,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


def _make_choppy_df(n: int = 500) -> pd.DataFrame:
    """Create choppy mean-reverting data — low ER values expected.

    Mean-reverting noise produces low ER since net displacement
    is small relative to total path length.
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)

    close = np.zeros(n)
    base = 100.0
    for i in range(n):
        noise = rng.normal(0, 2.0)
        close[i] = base + noise

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


class TestEfficiencyRatioTrend:
    """Tests for the EfficiencyRatioTrend strategy."""

    def test_default_params_instantiation(self):
        """Strategy can be instantiated with default parameters."""
        s = EfficiencyRatioTrend()
        assert s.name == "EfficiencyRatioTrend"
        assert s.timeframe == "1h"
        assert s.min_bars == 220
        assert s.version == "1.0.0"
        assert s.params["er_period"] == 20
        assert s.params["entry_threshold"] == 0.4
        assert s.params["exit_threshold"] == 0.2
        assert s.params["trend_period"] == 200

    def test_custom_params_instantiation(self):
        """Strategy can be instantiated with custom parameters."""
        s = EfficiencyRatioTrend(
            params={"er_period": 10, "entry_threshold": 0.3, "exit_threshold": 0.1}
        )
        assert s.params["er_period"] == 10
        assert s.params["entry_threshold"] == 0.3
        assert s.params["exit_threshold"] == 0.1

    def test_generate_signal_returns_correct_shape(self):
        """generate_signal() returns Series with correct shape and types."""
        df = _make_flat_df(500)
        s = EfficiencyRatioTrend()
        signal = s.generate_signal(df)

        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert (signal.index == df.index).all()
        assert signal.dtype == int

    def test_signal_values_valid(self):
        """Signal values are only -1, 0, 1."""
        df = _make_strong_uptrend_df(500)
        s = EfficiencyRatioTrend()
        signal = s.generate_signal(df)
        unique_vals = set(signal.unique())
        assert unique_vals.issubset({-1, 0, 1})

    def test_insufficient_bars_raises(self):
        """Short DataFrame raises StrategyError via preprocess."""
        df = _make_flat_df(150)
        s = EfficiencyRatioTrend()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_missing_columns_raises(self):
        """DataFrame missing required columns raises StrategyError."""
        df = pd.DataFrame(
            {"close": [100.0] * 500},
            index=pd.date_range("2024-01-01", periods=500, freq="1h"),
        )
        s = EfficiencyRatioTrend()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_uptrend_produces_long_signals(self):
        """Strong uptrend data should produce long signals."""
        df = _make_strong_uptrend_df(500)
        s = EfficiencyRatioTrend()
        signal = s.generate_signal(df)
        assert (signal == 1).any()

    def test_downtrend_produces_short_signals(self):
        """Strong downtrend data should produce short signals."""
        df = _make_strong_downtrend_df(500)
        s = EfficiencyRatioTrend()
        signal = s.generate_signal(df)
        assert (signal == -1).any()
