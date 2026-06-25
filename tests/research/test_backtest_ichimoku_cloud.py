"""Tests for IchimokuCloud strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_ichimoku_cloud import IchimokuCloud


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


def _make_uptrend_with_oscillation_df(n: int = 500) -> pd.DataFrame:
    """Create data with steady uptrend and small oscillations to trigger TK crosses.

    The uptrend keeps price above the cloud, and small oscillations
    cause the Tenkan (9) to cross above Kijun (26) frequently.
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)

    close = np.zeros(n)
    base = 100.0
    oscillation = 0.0
    osc_dir = 1
    for i in range(n):
        base += 0.1  # steady uptrend
        # Small oscillations to create TK crosses
        oscillation += osc_dir * rng.uniform(0.3, 1.2)
        if oscillation > 4.0:
            osc_dir = -1
        elif oscillation < -4.0:
            osc_dir = 1
        noise = rng.normal(0, 0.3)
        close[i] = base + oscillation + noise

    high = close + rng.uniform(1.0, 3.0, size=n)
    low = close - rng.uniform(0.5, 2.0, size=n)
    return pd.DataFrame(
        {
            "open": close - rng.uniform(0, 0.5, size=n),
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


def _make_downtrend_with_oscillation_df(n: int = 500) -> pd.DataFrame:
    """Create data with steady downtrend and oscillations for short TK crosses."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)

    close = np.zeros(n)
    base = 200.0
    oscillation = 0.0
    osc_dir = 1
    for i in range(n):
        base -= 0.1  # steady downtrend
        oscillation += osc_dir * rng.uniform(0.3, 1.2)
        if oscillation > 4.0:
            osc_dir = -1
        elif oscillation < -4.0:
            osc_dir = 1
        noise = rng.normal(0, 0.3)
        close[i] = base + oscillation + noise

    high = close + rng.uniform(0.5, 2.0, size=n)
    low = close - rng.uniform(1.0, 3.0, size=n)
    return pd.DataFrame(
        {
            "open": close + rng.uniform(0, 0.5, size=n),
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


class TestIchimokuCloud:
    """Tests for the IchimokuCloud strategy."""

    def test_default_params_instantiation(self):
        """Strategy can be instantiated with default parameters."""
        s = IchimokuCloud()
        assert s.name == "IchimokuCloud"
        assert s.timeframe == "1h"
        assert s.min_bars == 100
        assert s.version == "1.0.0"
        assert s.params["tenkan_period"] == 9
        assert s.params["kijun_period"] == 26
        assert s.params["senkou_b_period"] == 52
        assert s.params["displacement"] == 26

    def test_custom_params_instantiation(self):
        """Strategy can be instantiated with custom parameters."""
        s = IchimokuCloud(
            params={"tenkan_period": 7, "kijun_period": 22, "senkou_b_period": 44}
        )
        assert s.params["tenkan_period"] == 7
        assert s.params["kijun_period"] == 22
        assert s.params["senkou_b_period"] == 44

    def test_generate_signal_returns_correct_shape(self):
        """generate_signal() returns Series with correct shape and types."""
        df = _make_flat_df(500)
        s = IchimokuCloud()
        signal = s.generate_signal(df)

        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert (signal.index == df.index).all()
        assert signal.dtype == int

    def test_signal_values_valid(self):
        """Signal values are only -1, 0, 1."""
        df = _make_uptrend_with_oscillation_df(500)
        s = IchimokuCloud()
        signal = s.generate_signal(df)
        unique_vals = set(signal.unique())
        assert unique_vals.issubset({-1, 0, 1})

    def test_insufficient_bars_raises(self):
        """Short DataFrame raises StrategyError via preprocess."""
        df = _make_flat_df(80)
        s = IchimokuCloud()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_missing_columns_raises(self):
        """DataFrame missing required columns raises StrategyError."""
        df = pd.DataFrame(
            {"close": [100.0] * 500},
            index=pd.date_range("2024-01-01", periods=500, freq="1h"),
        )
        s = IchimokuCloud()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_uptrend_produces_long_signals(self):
        """Steady uptrend with oscillations should produce long signals."""
        df = _make_uptrend_with_oscillation_df(500)
        s = IchimokuCloud()
        signal = s.generate_signal(df)
        assert (signal == 1).any()

    def test_downtrend_produces_short_signals(self):
        """Steady downtrend with oscillations should produce short signals."""
        df = _make_downtrend_with_oscillation_df(500)
        s = IchimokuCloud()
        signal = s.generate_signal(df)
        assert (signal == -1).any()
