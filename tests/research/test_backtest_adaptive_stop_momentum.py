"""Tests for AdaptiveStopMomentum strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_adaptive_stop_momentum import AdaptiveStopMomentum


def _make_flat_df(n: int = 500) -> pd.DataFrame:
    """Create a flat-price OHLCV DataFrame for testing."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = np.full(n, 100.0)
    high = close + 1.0
    low = close - 1.0
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


def _make_uptrend_df(n: int = 500) -> pd.DataFrame:
    """Create data with a sharp price spike that triggers momentum entry."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = np.full(n, 100.0)
    # Sharp 10% spike at bar 200 to trigger momentum threshold
    close[200:350] = 120.0
    high = close + 1.0
    low = close - 1.0
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


def _make_downtrend_df(n: int = 500) -> pd.DataFrame:
    """Create data with a sharp price drop that triggers momentum entry."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = np.full(n, 100.0)
    # Sharp 10% drop at bar 200 to trigger momentum threshold
    close[200:350] = 80.0
    high = close + 1.0
    low = close - 1.0
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


class TestAdaptiveStopMomentum:
    """Tests for the AdaptiveStopMomentum strategy."""

    def test_default_params_instantiation(self):
        """Strategy can be instantiated with default parameters."""
        s = AdaptiveStopMomentum()
        assert s.name == "AdaptiveStopMomentum"
        assert s.timeframe == "1h"
        assert s.min_bars == 100
        assert s.version == "1.0.0"
        assert s.params["momentum_lookback"] == 20
        assert s.params["entry_threshold"] == 0.02
        assert s.params["atr_period"] == 14
        assert s.params["atr_multiplier"] == 2.5

    def test_custom_params_instantiation(self):
        """Strategy can be instantiated with custom parameters."""
        s = AdaptiveStopMomentum(
            params={"momentum_lookback": 10, "entry_threshold": 0.03}
        )
        assert s.params["momentum_lookback"] == 10
        assert s.params["entry_threshold"] == 0.03
        assert s.params["atr_period"] == 14  # unchanged default

    def test_generate_signal_returns_correct_shape(self):
        """generate_signal() returns Series with correct shape and types."""
        df = _make_flat_df(500)
        s = AdaptiveStopMomentum()
        signal = s.generate_signal(df)

        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert (signal.index == df.index).all()
        assert signal.dtype == int

    def test_signal_values_valid(self):
        """Signal values are only -1, 0, 1."""
        df = _make_uptrend_df(500)
        s = AdaptiveStopMomentum()
        signal = s.generate_signal(df)
        unique_vals = set(signal.unique())
        assert unique_vals.issubset({-1, 0, 1})

    def test_insufficient_bars_raises(self):
        """Short DataFrame raises StrategyError via preprocess."""
        df = _make_flat_df(50)  # fewer than min_bars=100
        s = AdaptiveStopMomentum()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_missing_columns_raises(self):
        """DataFrame missing required columns raises StrategyError."""
        df = pd.DataFrame(
            {"close": [100.0] * 500},
            index=pd.date_range("2024-01-01", periods=500, freq="1h"),
        )
        s = AdaptiveStopMomentum()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_uptrend_produces_signal(self):
        """In a strong uptrend, momentum threshold should trigger entry."""
        df = _make_uptrend_df(500)
        s = AdaptiveStopMomentum()
        signal = s.generate_signal(df)
        assert (signal != 0).any()

    def test_downtrend_produces_signal(self):
        """In a strong downtrend, momentum threshold should trigger entry."""
        df = _make_downtrend_df(500)
        s = AdaptiveStopMomentum()
        signal = s.generate_signal(df)
        assert (signal != 0).any()

    def test_flat_market_produces_no_signal(self):
        """Flat market should produce no entry signals."""
        df = _make_flat_df(500)
        s = AdaptiveStopMomentum()
        signal = s.generate_signal(df)
        # In a perfectly flat market, momentum never crosses threshold
        assert (signal == 0).all()
