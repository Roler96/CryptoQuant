"""Tests for McGinleyDynamicTrend strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from cryptoquant.strategy.signals import mcginley_dynamic
from research.backtest_mcginley_dynamic_trend import McGinleyDynamicTrend


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
    """Create trending data with increasing price."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    trend = np.linspace(100.0, 200.0, n)
    noise = np.random.default_rng(42).normal(0, 2.0, n)
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


def _make_downtrend_df(n: int = 500) -> pd.DataFrame:
    """Create trending data with decreasing price."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    trend = np.linspace(200.0, 100.0, n)
    noise = np.random.default_rng(42).normal(0, 2.0, n)
    close = trend + noise
    return pd.DataFrame(
        {
            "open": close + 1.0,
            "high": close + 2.0,
            "low": close - 2.0,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


class TestMcGinleyDynamicTrend:
    """Tests for McGinleyDynamicTrend strategy."""

    def test_initialization(self):
        """Strategy initializes with default params."""
        s = McGinleyDynamicTrend({})
        assert s.name == "McGinleyDynamicTrend"
        assert s.params["md_period"] == 20
        assert s.params["md_k"] == 0.6
        assert s.params["trend_period"] == 200

    def test_custom_params(self):
        """Custom params override defaults."""
        s = McGinleyDynamicTrend(
            {"md_period": 14, "md_k": 0.5, "trend_period": 100}
        )
        assert s.params["md_period"] == 14
        assert s.params["md_k"] == 0.5
        assert s.params["trend_period"] == 100

    def test_insufficient_bars(self):
        """Strategy raises StrategyError with too few bars."""
        s = McGinleyDynamicTrend({})
        df = _make_flat_df(n=50)
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_flat_price_signal_valid(self):
        """Flat price produces valid signal format."""
        s = McGinleyDynamicTrend({})
        df = _make_flat_df(n=500)
        signal = s.generate_signal(df)
        assert len(signal) == len(df)
        assert signal.dtype == int
        assert set(signal.unique()).issubset({-1, 0, 1})

    def test_uptrend_generates_long_signal(self):
        """Uptrend should generate long signals."""
        s = McGinleyDynamicTrend({})
        df = _make_uptrend_df(n=500)
        signal = s.generate_signal(df)
        assert len(signal) == len(df)
        assert 1 in signal.values

    def test_downtrend_generates_short_signal(self):
        """Downtrend should generate short signals."""
        s = McGinleyDynamicTrend({})
        df = _make_downtrend_df(n=500)
        signal = s.generate_signal(df)
        assert len(signal) == len(df)
        assert -1 in signal.values

    def test_mcginley_indicator_output(self):
        """McGinley Dynamic produces valid Series after warmup."""
        df = _make_uptrend_df(n=500)
        md = mcginley_dynamic(df, period=20, k=0.6)
        assert len(md) == len(df)
        assert isinstance(md, pd.Series)
        # After warmup, values should be non-NaN
        assert md.iloc[200:].notna().any()
        # McGinley Dynamic should track price direction
        assert md.iloc[-1] > md.iloc[200]
