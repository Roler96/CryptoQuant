"""Tests for PsarTrend strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_psar_trend import PsarTrend


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
    """Create data with strong uptrend to trigger PSAR long entry."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)

    close = np.zeros(n)
    base = 100.0
    for i in range(n):
        base += 0.15  # steady climb
        noise = rng.normal(0, 1.0)
        close[i] = base + noise

    high = close + 3.0
    low = close - 1.5
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


def _make_strong_downtrend_df(n: int = 500) -> pd.DataFrame:
    """Create data with strong downtrend for short entry testing."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)

    close = np.zeros(n)
    base = 200.0
    for i in range(n):
        base -= 0.15
        noise = rng.normal(0, 1.0)
        close[i] = base + noise

    high = close + 1.5
    low = close - 3.0
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


class TestPsarTrend:
    """Tests for the PsarTrend strategy."""

    def test_default_params_instantiation(self):
        """Strategy can be instantiated with default parameters."""
        s = PsarTrend()
        assert s.name == "PsarTrend"
        assert s.timeframe == "1h"
        assert s.min_bars == 300
        assert s.version == "1.0.0"
        assert s.params["psar_af_start"] == 0.02
        assert s.params["psar_af_step"] == 0.02
        assert s.params["psar_af_max"] == 0.20
        assert s.params["trend_period"] == 200

    def test_custom_params_instantiation(self):
        """Strategy can be instantiated with custom parameters."""
        s = PsarTrend(
            params={"psar_af_start": 0.01, "psar_af_max": 0.15, "trend_period": 100}
        )
        assert s.params["psar_af_start"] == 0.01
        assert s.params["psar_af_max"] == 0.15
        assert s.params["trend_period"] == 100

    def test_generate_signal_returns_correct_shape(self):
        """generate_signal() returns Series with correct shape and types."""
        df = _make_flat_df(500)
        s = PsarTrend()
        signal = s.generate_signal(df)

        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert (signal.index == df.index).all()
        assert signal.dtype == int

    def test_signal_values_valid(self):
        """Signal values are only -1, 0, 1."""
        df = _make_strong_uptrend_df(500)
        s = PsarTrend()
        signal = s.generate_signal(df)
        unique_vals = set(signal.unique())
        assert unique_vals.issubset({-1, 0, 1})

    def test_insufficient_bars_raises(self):
        """Short DataFrame raises StrategyError via preprocess."""
        df = _make_flat_df(200)
        s = PsarTrend()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_missing_columns_raises(self):
        """DataFrame missing required columns raises StrategyError."""
        df = pd.DataFrame(
            {"close": [100.0] * 500},
            index=pd.date_range("2024-01-01", periods=500, freq="1h"),
        )
        s = PsarTrend()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_uptrend_produces_long_signals(self):
        """Strong uptrend data should produce long signals."""
        df = _make_strong_uptrend_df(500)
        s = PsarTrend()
        signal = s.generate_signal(df)
        assert (signal == 1).any()

    def test_downtrend_produces_short_signals(self):
        """Strong downtrend data should produce short signals."""
        df = _make_strong_downtrend_df(500)
        s = PsarTrend()
        signal = s.generate_signal(df)
        assert (signal == -1).any()
