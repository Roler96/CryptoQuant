"""Tests for RSIBBMeanReversion strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_rsi_bb_mean_reversion import RSIBBMeanReversion


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


def _make_oversold_df(n: int = 500) -> pd.DataFrame:
    """Create data where price drops sharply (RSI becomes oversold) then recovers."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = np.full(n, 100.0)
    # Sharp drop to trigger oversold RSI
    close[200:210] = np.linspace(100, 85, 10)
    close[210:220] = 85.0  # stay low
    # Recovery
    close[220:300] = np.linspace(85, 100, 80)
    close[300:] = 100.0

    high = close + 1.0
    low = close - 1.0
    opens = close - 0.5

    return pd.DataFrame(
        {
            "open": opens,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


def _make_overbought_df(n: int = 500) -> pd.DataFrame:
    """Create data where price spikes sharply (RSI becomes overbought) then falls."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = np.full(n, 100.0)
    # Sharp spike to trigger overbought RSI
    close[200:210] = np.linspace(100, 120, 10)
    close[210:220] = 120.0  # stay high
    # Decline
    close[220:300] = np.linspace(120, 100, 80)
    close[300:] = 100.0

    high = close + 1.0
    low = close - 1.0
    opens = close - 0.5

    return pd.DataFrame(
        {
            "open": opens,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


class TestRSIBBMeanReversion:
    """Tests for the RSIBBMeanReversion strategy."""

    def test_default_params_instantiation(self):
        """Strategy can be instantiated with default parameters."""
        s = RSIBBMeanReversion()
        assert s.name == "RSIBBMeanReversion"
        assert s.timeframe == "1h"
        assert s.min_bars == 200
        assert s.version == "1.0.0"
        assert s.params["rsi_period"] == 14
        assert s.params["bb_period"] == 20
        assert s.params["bb_std"] == 2.0
        assert s.params["oversold"] == 35
        assert s.params["overbought"] == 65

    def test_custom_params_instantiation(self):
        """Strategy can be instantiated with custom parameters."""
        s = RSIBBMeanReversion(
            params={"rsi_period": 10, "oversold": 30, "overbought": 70}
        )
        assert s.params["rsi_period"] == 10
        assert s.params["oversold"] == 30
        assert s.params["overbought"] == 70
        # Unchanged defaults
        assert s.params["bb_period"] == 20

    def test_generate_signal_returns_correct_shape(self):
        """generate_signal() returns Series with correct shape and types."""
        df = _make_flat_df(500)
        s = RSIBBMeanReversion()
        signal = s.generate_signal(df)

        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert (signal.index == df.index).all()
        assert signal.dtype == int

    def test_signal_values_valid(self):
        """Signal values are only -1, 0, 1."""
        df = _make_oversold_df(500)
        s = RSIBBMeanReversion()
        signal = s.generate_signal(df)
        unique_vals = set(signal.unique())
        assert unique_vals.issubset({-1, 0, 1})

    def test_insufficient_bars_raises(self):
        """Short DataFrame raises StrategyError via preprocess."""
        df = _make_flat_df(50)  # fewer than min_bars=200
        s = RSIBBMeanReversion()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_missing_columns_raises(self):
        """DataFrame missing required columns raises StrategyError."""
        df = pd.DataFrame(
            {"close": [100.0] * 500},
            index=pd.date_range("2024-01-01", periods=500, freq="1h"),
        )
        s = RSIBBMeanReversion()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_oversold_produces_signal(self):
        """A sharp price drop should eventually produce some non-zero signals."""
        df = _make_oversold_df(500)
        s = RSIBBMeanReversion()
        signal = s.generate_signal(df)
        # At least some bars should produce a signal in oversold conditions
        assert (signal != 0).any()

    def test_overbought_produces_signal(self):
        """A sharp price spike should eventually produce some non-zero signals."""
        df = _make_overbought_df(500)
        s = RSIBBMeanReversion()
        signal = s.generate_signal(df)
        assert (signal != 0).any()
