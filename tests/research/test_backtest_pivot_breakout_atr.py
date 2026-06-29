"""Tests for PivotBreakoutATR strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_pivot_breakout_atr import PivotBreakoutATR


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


def _make_uptrend_with_pivots(n: int = 500) -> pd.DataFrame:
    """Create uptrend with swing highs/lows for pivot breakout testing."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)

    close = np.zeros(n)
    base = 100.0
    for i in range(n):
        # Alternate between strong trend and pullback to create pivot structure
        phase = i % 40
        if phase < 30:
            base += 0.20  # trending up
        else:
            base -= 0.05  # mild pullback creates pivot low
        noise = rng.normal(0, 0.3)
        close[i] = base + noise

    high = close + np.abs(rng.normal(1.5, 0.5, n))
    low = close - np.abs(rng.normal(1.0, 0.3, n))
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 5000.0),
        },
        index=dates,
    )


def _make_downtrend_with_pivots(n: int = 500) -> pd.DataFrame:
    """Create downtrend with swing highs/lows for pivot breakout testing.

    Creates sawtooth pattern: downtrend with periodic bounces creating pivot
    highs, then breakdown through pivot lows with wide-bar ATR expansion.
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)

    close = np.zeros(n)
    base = 200.0
    for i in range(n):
        phase = i % 50
        if phase < 30:
            base -= 0.15  # trending down
        elif phase < 40:
            base += 0.15  # bounce creates pivot high
        else:
            base -= 0.40  # breakdown with strong momentum
        noise = rng.normal(0, 0.2)
        close[i] = base + noise

    # Wide bars during breakdown phases to trigger ATR expansion
    breakout_phase = np.array([i % 50 >= 40 for i in range(n)])
    bar_widen = np.where(breakout_phase, 4.0, 1.5)
    high = close + np.abs(rng.normal(bar_widen * 0.8, 0.2, n))
    low = close - np.abs(rng.normal(bar_widen, 0.3, n))
    return pd.DataFrame(
        {
            "open": close + 0.1,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 5000.0),
        },
        index=dates,
    )


class TestPivotBreakoutATR:
    """Tests for the PivotBreakoutATR strategy."""

    def test_default_params_instantiation(self):
        """Strategy can be instantiated with default parameters."""
        s = PivotBreakoutATR()
        assert s.name == "PivotBreakoutATR"
        assert s.timeframe == "1h"
        assert s.min_bars == 100
        assert s.version == "1.0.0"
        assert s.params["pivot_bars"] == 5
        assert s.params["atr_period"] == 14
        assert s.params["expansion_mult"] == 1.5

    def test_custom_params_instantiation(self):
        """Strategy can be instantiated with custom parameters."""
        s = PivotBreakoutATR(params={
            "pivot_bars": 3,
            "atr_period": 10,
            "expansion_mult": 2.0,
        })
        assert s.params["pivot_bars"] == 3
        assert s.params["atr_period"] == 10
        assert s.params["expansion_mult"] == 2.0

    def test_generate_signal_returns_correct_shape(self):
        """generate_signal() returns Series with correct shape and types."""
        df = _make_flat_df(500)
        s = PivotBreakoutATR()
        signal = s.generate_signal(df)

        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert (signal.index == df.index).all()
        assert signal.dtype == int

    def test_signal_values_valid(self):
        """Signal values are only -1, 0, 1."""
        df = _make_uptrend_with_pivots(500)
        s = PivotBreakoutATR()
        signal = s.generate_signal(df)
        unique_vals = set(signal.unique())
        assert unique_vals.issubset({-1, 0, 1})

    def test_insufficient_bars_raises(self):
        """Short DataFrame raises StrategyError via preprocess."""
        df = _make_flat_df(50)
        s = PivotBreakoutATR()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_missing_columns_raises(self):
        """DataFrame missing required columns raises StrategyError."""
        df = pd.DataFrame(
            {"close": [100.0] * 500},
            index=pd.date_range("2024-01-01", periods=500, freq="1h"),
        )
        s = PivotBreakoutATR()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_uptrend_produces_long_signals(self):
        """Uptrend data with pivot structure should produce long signals."""
        df = _make_uptrend_with_pivots(500)
        s = PivotBreakoutATR()
        signal = s.generate_signal(df)
        assert (signal == 1).any()

    def test_downtrend_produces_short_signals(self):
        """Downtrend data with pivot structure should produce short signals."""
        df = _make_downtrend_with_pivots(500)
        s = PivotBreakoutATR()
        signal = s.generate_signal(df)
        assert (signal == -1).any()
