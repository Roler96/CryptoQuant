"""Tests for IchimokuTKCrossTrend strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_ichimoku_tk_cross_trend import IchimokuTKCrossTrend


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


def _make_uptrend_crossing_df(n: int = 500) -> pd.DataFrame:
    """Create data with uptrend + rolling highs that will trigger TK cross up.

    Simulates a scenario where price rises gradually with expanding highs,
    so Tenkan-sen (9-period mid-point) eventually crosses above Kijun-sen
    (26-period mid-point).
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)

    close = np.zeros(n)
    base = 100.0
    for i in range(n):
        # Steady uptrend with acceleration in second half
        if i < 250:
            base += 0.02
        else:
            base += 0.10
        noise = rng.normal(0, 0.5)
        close[i] = base + noise

    # Expanding range in the acceleration phase to push Tenkan ahead of Kijun
    high = np.maximum(close + 1.0, close + np.linspace(1, 5, n))
    low = close - 0.8
    open_ = close - 0.2
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 5000.0),
        },
        index=dates,
    )


def _make_downtrend_crossing_df(n: int = 500) -> pd.DataFrame:
    """Create data with downtrend + rolling lows that will trigger TK cross down."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)

    close = np.zeros(n)
    base = 200.0
    for i in range(n):
        if i < 250:
            base -= 0.02
        else:
            base -= 0.10
        noise = rng.normal(0, 0.5)
        close[i] = base + noise

    # Expanding range downward in the acceleration phase
    low = np.minimum(close - 1.0, close - np.linspace(1, 5, n))
    high = close + 0.8
    open_ = close + 0.2
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 5000.0),
        },
        index=dates,
    )


class TestIchimokuTKCrossTrend:
    """Tests for the IchimokuTKCrossTrend strategy."""

    def test_default_params_instantiation(self):
        """Strategy can be instantiated with default parameters."""
        s = IchimokuTKCrossTrend()
        assert s.name == "IchimokuTKCrossTrend"
        assert s.timeframe == "1h"
        assert s.min_bars == 200
        assert s.version == "1.0.0"
        assert s.params["tenkan_period"] == 9
        assert s.params["kijun_period"] == 26
        assert s.params["trend_period"] == 200

    def test_custom_params_instantiation(self):
        """Strategy can be instantiated with custom parameters."""
        s = IchimokuTKCrossTrend(params={
            "tenkan_period": 7, "kijun_period": 22, "trend_period": 100
        })
        assert s.params["tenkan_period"] == 7
        assert s.params["kijun_period"] == 22
        assert s.params["trend_period"] == 100

    def test_generate_signal_returns_correct_shape(self):
        """generate_signal() returns Series with correct shape and types."""
        df = _make_flat_df(500)
        s = IchimokuTKCrossTrend()
        signal = s.generate_signal(df)

        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert (signal.index == df.index).all()
        assert signal.dtype == int

    def test_signal_values_valid(self):
        """Signal values are only -1, 0, 1."""
        df = _make_uptrend_crossing_df(500)
        s = IchimokuTKCrossTrend()
        signal = s.generate_signal(df)
        unique_vals = set(signal.unique())
        assert unique_vals.issubset({-1, 0, 1})

    def test_insufficient_bars_raises(self):
        """Short DataFrame raises StrategyError via preprocess."""
        df = _make_flat_df(150)
        s = IchimokuTKCrossTrend()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_missing_columns_raises(self):
        """DataFrame missing required columns raises StrategyError."""
        df = pd.DataFrame(
            {"close": [100.0] * 500},
            index=pd.date_range("2024-01-01", periods=500, freq="1h"),
        )
        s = IchimokuTKCrossTrend()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_uptrend_produces_long_signals(self):
        """Uptrend crossing data should produce long signals."""
        df = _make_uptrend_crossing_df(500)
        s = IchimokuTKCrossTrend()
        signal = s.generate_signal(df)
        assert (signal == 1).any()

    def test_downtrend_produces_short_signals(self):
        """Downtrend crossing data should produce short signals."""
        df = _make_downtrend_crossing_df(500)
        s = IchimokuTKCrossTrend()
        signal = s.generate_signal(df)
        assert (signal == -1).any()
