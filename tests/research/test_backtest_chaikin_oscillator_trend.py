"""Tests for ChaikinOscillatorTrend strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_chaikin_oscillator_trend import ChaikinOscillatorTrend


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
    """Create variable OHLCV data with uptrend + sharp pullback + recovery.

    Variable bar structure (not constant MFM) allows Chaikin Oscillator
    to cross zero during the pullback, then re-cross on recovery.
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)

    trend = np.linspace(100.0, 200.0, n)
    # First 150 bars: smooth uptrend
    close_1 = trend[:150] + rng.normal(0, 2.0, 150)
    # Bars 150-200: sharp pullback (close drops ~15%)
    trend_mid = trend[150:200]
    close_2 = trend_mid - 15.0 + rng.normal(0, 3.0, 50)
    # Bars 200+: recovery to trend
    close_3 = trend[200:] + rng.normal(0, 2.0, n - 200)
    close = np.concatenate([close_1, close_2, close_3])

    # Variable bar structure
    bar_range = np.abs(rng.normal(3.0, 1.0, n))
    open_ = close + rng.normal(-1.0, 1.0, n)  # variable open position
    high = np.maximum(open_, close) + np.abs(rng.normal(0.5, 0.5, n))
    low = np.minimum(open_, close) - np.abs(rng.normal(0.5, 0.5, n))

    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close,
         "volume": np.full(n, 1000.0)},
        index=dates,
    )


def _make_downtrend_df(n: int = 500) -> pd.DataFrame:
    """Create variable OHLCV data with downtrend + sharp rally + resume.

    Variable bar structure allows Chaikin Oscillator to cross during rally.
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)

    trend = np.linspace(200.0, 100.0, n)
    close_1 = trend[:150] + rng.normal(0, 2.0, 150)
    trend_mid = trend[150:200]
    close_2 = trend_mid + 15.0 + rng.normal(0, 3.0, 50)
    close_3 = trend[200:] + rng.normal(0, 2.0, n - 200)
    close = np.concatenate([close_1, close_2, close_3])

    bar_range = np.abs(rng.normal(3.0, 1.0, n))
    open_ = close + rng.normal(1.0, 1.0, n)
    high = np.maximum(open_, close) + np.abs(rng.normal(0.5, 0.5, n))
    low = np.minimum(open_, close) - np.abs(rng.normal(0.5, 0.5, n))

    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close,
         "volume": np.full(n, 1000.0)},
        index=dates,
    )


class TestChaikinOscillatorTrend:
    """Tests for ChaikinOscillatorTrend strategy."""

    def test_initialization(self):
        """Strategy initializes with default params."""
        s = ChaikinOscillatorTrend({})
        assert s.name == "ChaikinOscillatorTrend"
        assert s.params["chaikin_fast"] == 3
        assert s.params["chaikin_slow"] == 10
        assert s.params["trend_period"] == 200
        assert s.params["atr_period"] == 14
        assert s.params["trailing_mult"] == 2.0

    def test_custom_params(self):
        """Custom params override defaults."""
        s = ChaikinOscillatorTrend(
            {"chaikin_fast": 5, "chaikin_slow": 20, "trend_period": 100}
        )
        assert s.params["chaikin_fast"] == 5
        assert s.params["chaikin_slow"] == 20
        assert s.params["trend_period"] == 100

    def test_insufficient_bars(self):
        """Strategy raises StrategyError with too few bars."""
        s = ChaikinOscillatorTrend({})
        df = _make_flat_df(n=50)
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_flat_price_no_signals(self):
        """Flat price produces valid output — no NaN, correct dtype."""
        s = ChaikinOscillatorTrend({})
        df = _make_flat_df(n=500)
        signal = s.generate_signal(df)
        assert len(signal) == len(df)
        assert signal.dtype == int
        assert set(signal.unique()).issubset({-1, 0, 1})

    def test_uptrend_generates_long_signal(self):
        """Uptrend should generate at least some long signals."""
        s = ChaikinOscillatorTrend({})
        df = _make_uptrend_df(n=500)
        signal = s.generate_signal(df)
        assert len(signal) == len(df)
        assert 1 in signal.values

    def test_downtrend_generates_short_signal(self):
        """Downtrend should generate short signals."""
        s = ChaikinOscillatorTrend({})
        df = _make_downtrend_df(n=500)
        signal = s.generate_signal(df)
        assert len(signal) == len(df)
        assert -1 in signal.values
