"""Tests for BBandBreakoutVolume strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_bband_breakout_volume import BBandBreakoutVolume


def _make_flat_df(n: int = 500) -> pd.DataFrame:
    """Create a flat-price OHLCV DataFrame for testing."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = np.full(n, 100.0)
    high = close + 0.5
    low = close - 0.5
    opens = close - 0.1
    # Add volume spikes on every bar to ensure volume > vol_sma
    volume = np.full(n, 1000.0)
    return pd.DataFrame(
        {"open": opens, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


def _make_uptrend_df(n: int = 500) -> pd.DataFrame:
    """Create data with a sharp price spike that triggers BB breakout."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = np.full(n, 100.0)
    high = close + 0.5
    low = close - 0.5
    volume = np.full(n, 1000.0)
    # Sharp spike to force price above BB upper band
    close[250:260] = 130.0
    high[250:260] = 130.5
    low[250:260] = 129.5
    volume[250:260] = 2000.0  # Above volume SMA
    opens = close - 0.1
    return pd.DataFrame(
        {"open": opens, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


def _make_downtrend_df(n: int = 500) -> pd.DataFrame:
    """Create data with a sharp price drop that triggers BB breakdown."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = np.full(n, 100.0)
    high = close + 0.5
    low = close - 0.5
    volume = np.full(n, 1000.0)
    # Sharp drop to force price below BB lower band
    close[250:260] = 70.0
    high[250:260] = 70.5
    low[250:260] = 69.5
    volume[250:260] = 2000.0  # Above volume SMA
    opens = close - 0.1
    return pd.DataFrame(
        {"open": opens, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


class TestBBandBreakoutVolume:
    """Tests for the BBandBreakoutVolume strategy."""

    def test_default_params_instantiation(self):
        """Strategy can be instantiated with default parameters."""
        s = BBandBreakoutVolume()
        assert s.name == "BBandBreakoutVolume"
        assert s.timeframe == "1h"
        assert s.min_bars == 100
        assert s.version == "1.0.0"
        assert s.params["bb_period"] == 20
        assert s.params["bb_std"] == 2.0
        assert s.params["vol_period"] == 20

    def test_custom_params_instantiation(self):
        """Strategy can be instantiated with custom parameters."""
        s = BBandBreakoutVolume(
            params={"bb_period": 10, "bb_std": 1.5, "vol_period": 10}
        )
        assert s.params["bb_period"] == 10
        assert s.params["bb_std"] == 1.5
        assert s.params["vol_period"] == 10

    def test_generate_signal_returns_correct_shape(self):
        """generate_signal() returns Series with correct shape and types."""
        df = _make_flat_df(500)
        s = BBandBreakoutVolume()
        signal = s.generate_signal(df)

        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert (signal.index == df.index).all()
        assert signal.dtype == int

    def test_signal_values_valid(self):
        """Signal values are only -1, 0, 1."""
        df = _make_uptrend_df(500)
        s = BBandBreakoutVolume()
        signal = s.generate_signal(df)
        unique_vals = set(signal.unique())
        assert unique_vals.issubset({-1, 0, 1})

    def test_insufficient_bars_raises(self):
        """Short DataFrame raises StrategyError via preprocess."""
        df = _make_flat_df(50)  # fewer than min_bars=100
        s = BBandBreakoutVolume()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_missing_columns_raises(self):
        """DataFrame missing required columns raises StrategyError."""
        df = pd.DataFrame(
            {"close": [100.0] * 500},
            index=pd.date_range("2024-01-01", periods=500, freq="1h"),
        )
        s = BBandBreakoutVolume()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_uptrend_produces_signal(self):
        """In a sharp uptrend, BB breakout should eventually produce signals."""
        df = _make_uptrend_df(500)
        s = BBandBreakoutVolume()
        signal = s.generate_signal(df)
        assert (signal != 0).any()

    def test_downtrend_produces_signal(self):
        """In a sharp downtrend, BB breakdown should eventually produce signals."""
        df = _make_downtrend_df(500)
        s = BBandBreakoutVolume()
        signal = s.generate_signal(df)
        assert (signal != 0).any()
