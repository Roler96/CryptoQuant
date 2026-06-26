"""Tests for AwesomeOscillatorTrend strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_awesome_oscillator_trend import AwesomeOscillatorTrend


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


def _make_oscillating_df(n: int = 500) -> pd.DataFrame:
    """Create oscillating data (sine wave) for AO crossover testing."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    t = np.linspace(0, 8 * np.pi, n)
    close = 100.0 + 10.0 * np.sin(t)
    high = close + 2.0
    low = close - 2.0
    return pd.DataFrame(
        {
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


def _make_uptrend_with_oscillation_df(n: int = 500) -> pd.DataFrame:
    """Create uptrend data with oscillations for long entry testing."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)
    t = np.linspace(0, 6 * np.pi, n)
    close = 100.0 + 0.08 * np.arange(n) + 4.0 * np.sin(t) + rng.normal(0, 0.5, n)
    high = close + 2.0
    low = close - 2.0
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


def _make_downtrend_with_oscillation_df(n: int = 500) -> pd.DataFrame:
    """Create downtrend data with oscillations for short entry testing."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)
    t = np.linspace(0, 6 * np.pi, n)
    close = 200.0 - 0.08 * np.arange(n) + 4.0 * np.sin(t) + rng.normal(0, 0.5, n)
    high = close + 2.0
    low = close - 2.0
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


class TestAwesomeOscillatorTrend:
    """Tests for the AwesomeOscillatorTrend strategy."""

    def test_default_params_instantiation(self):
        """Strategy can be instantiated with default parameters."""
        s = AwesomeOscillatorTrend()
        assert s.name == "AwesomeOscillatorTrend"
        assert s.timeframe == "1h"
        assert s.min_bars == 300
        assert s.version == "1.0.0"
        assert s.params["ao_fast"] == 5
        assert s.params["ao_slow"] == 34
        assert s.params["trend_period"] == 200

    def test_custom_params_instantiation(self):
        """Strategy can be instantiated with custom parameters."""
        s = AwesomeOscillatorTrend(
            params={"ao_fast": 3, "ao_slow": 21, "trend_period": 100}
        )
        assert s.params["ao_fast"] == 3
        assert s.params["ao_slow"] == 21
        assert s.params["trend_period"] == 100

    def test_signal_output_shape(self):
        """Signal output has same length and index as input DataFrame."""
        df = _make_flat_df(500)
        s = AwesomeOscillatorTrend()
        signal = s.generate_signal(df)
        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert signal.index.equals(df.index)
        assert signal.dtype == int

    def test_signal_values_valid(self):
        """All signal values are in {1, 0, -1}."""
        df = _make_flat_df(500)
        s = AwesomeOscillatorTrend()
        signal = s.generate_signal(df)
        assert signal.isin([1, 0, -1]).all()

    def test_no_signal_on_flat_data(self):
        """Flat price data produces zero signals (AO stays at 0, no crossover)."""
        df = _make_flat_df(500)
        s = AwesomeOscillatorTrend()
        signal = s.generate_signal(df)
        # AO = 0 with flat data, no crossover
        assert (signal == 0).all()

    def test_insufficient_bars_raises(self):
        """Strategy raises StrategyError when DataFrame is too short."""
        df = _make_flat_df(50)
        s = AwesomeOscillatorTrend()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_generates_long_signals_in_uptrend(self):
        """Oscillating uptrend produces long crossover signals."""
        df = _make_uptrend_with_oscillation_df(500)
        s = AwesomeOscillatorTrend()
        signal = s.generate_signal(df)
        assert (signal == 1).any(), "Expected some long signals in uptrend"

    def test_generates_short_signals_in_downtrend(self):
        """Oscillating downtrend produces short crossover signals."""
        df = _make_downtrend_with_oscillation_df(500)
        s = AwesomeOscillatorTrend()
        signal = s.generate_signal(df)
        assert (signal == -1).any(), "Expected some short signals in downtrend"

    def test_no_position_overlap(self):
        """Long and short signals never occur on the same bar."""
        df = _make_oscillating_df(500)
        s = AwesomeOscillatorTrend()
        signal = s.generate_signal(df)
        long_bars = signal == 1
        short_bars = signal == -1
        assert not (long_bars & short_bars).any()
