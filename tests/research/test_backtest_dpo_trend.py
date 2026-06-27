"""Tests for DPOTrend strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_dpo_trend import DPOTrend


def _make_flat_df(n: int = 500) -> pd.DataFrame:
    """Create flat-price OHLCV DataFrame for testing."""
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


def _make_cycle_df(n: int = 800) -> pd.DataFrame:
    """Create data with clear cyclical pattern (sine wave + trend).

    Price oscillates around a slow uptrend, creating DPO zero-crosses.
    ATR expansion is triggered when cycle amplitude widens.
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)

    # Slow uptrend
    trend = np.linspace(100, 120, n)

    # Cycle: sine wave with amplitude expansion in phase 2 (300-500)
    amplitude = np.full(n, 0.5)
    amplitude[300:500] = 3.0  # Expanded amplitude → ATR expansion

    cycle = amplitude * np.sin(np.linspace(0, 12 * np.pi, n))
    cycle += rng.normal(0, 0.1, n)

    close = trend + cycle
    high = close + np.abs(rng.normal(0, 0.5, n))
    low = close - np.abs(rng.normal(0, 0.5, n))

    # Ensure high > close and low < close
    high = np.maximum(high, close + 0.1)
    low = np.minimum(low, close - 0.1)

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


class TestDPOTrend:
    """Tests for DPOTrend strategy."""

    def test_default_params_instantiation(self):
        """Strategy can be instantiated with default parameters."""
        s = DPOTrend()
        assert s.name == "DPOTrend"
        assert s.timeframe == "1h"
        assert s.min_bars == 200
        assert s.version == "1.0.0"
        assert s.params["dpo_period"] == 20
        assert s.params["atr_period"] == 14
        assert s.params["expansion_mult"] == 1.5

    def test_custom_params_instantiation(self):
        """Strategy can be instantiated with custom parameters."""
        s = DPOTrend(
            params={"dpo_period": 10, "atr_period": 7, "expansion_mult": 2.0}
        )
        assert s.params["dpo_period"] == 10
        assert s.params["atr_period"] == 7
        assert s.params["expansion_mult"] == 2.0

    def test_generate_signal_returns_correct_shape(self):
        """generate_signal() returns Series with correct shape and types."""
        df = _make_flat_df(500)
        s = DPOTrend()
        signal = s.generate_signal(df)
        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert (signal.index == df.index).all()
        assert signal.dtype == int

    def test_signal_values_valid(self):
        """Signal values are only -1, 0, 1."""
        df = _make_cycle_df(600)
        s = DPOTrend()
        signal = s.generate_signal(df)
        unique_vals = set(signal.unique())
        assert unique_vals.issubset({-1, 0, 1})

    def test_insufficient_bars_raises(self):
        """Short DataFrame raises StrategyError via preprocess."""
        df = _make_flat_df(100)
        s = DPOTrend()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_missing_columns_raises(self):
        """DataFrame missing required columns raises StrategyError."""
        df = pd.DataFrame(
            {"close": [100.0] * 500},
            index=pd.date_range("2024-01-01", periods=500, freq="1h"),
        )
        s = DPOTrend()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_cycle_data_runs_without_error(self):
        """Strategy runs on cyclical data without error."""
        df = _make_cycle_df(800)
        s = DPOTrend()
        signal = s.generate_signal(df)
        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert signal.dtype == int
        unique_vals = set(signal.unique())
        assert unique_vals.issubset({-1, 0, 1})

    def test_dpo_computation_returns_finite_values(self):
        """DPO computation returns finite values in the valid range.

        The DPO calculation uses forward displacement (.shift(-half)), so
        the last `dpo_period//2+1` bars are always NaN. This is expected.
        """
        df = _make_cycle_df(500)
        s = DPOTrend()
        close = df["close"]
        dpo = s._compute_dpo(close, period=20)
        # Valid range: after warmup, before displacement NaN tail
        start = 50    # well after SMA warmup
        end = -12      # before displacement NaN (half=11)
        valid = dpo.iloc[start:end]
        assert valid.notna().all()
        assert np.isfinite(valid).all()
