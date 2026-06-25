"""Tests for KeltnerBreakoutADX strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_keltner_breakout_adx import KeltnerBreakoutADX


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
    """Create data with a sharp sustained uptrend + volatility + volume."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = np.full(n, 100.0)
    # Gradual rise then sharp spike above KC upper band with high volume
    close[200:300] = np.linspace(100, 120, 100)
    close[300:450] = 125.0

    high = close + 1.0
    low = close - 0.5
    opens = close - 0.2
    volume = np.full(n, 1000.0)
    volume[300:450] = 5000.0  # high volume spike

    return pd.DataFrame(
        {
            "open": opens,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=dates,
    )


def _make_downtrend_df(n: int = 500) -> pd.DataFrame:
    """Create data with a sharp sustained downtrend + volatility + volume."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = np.full(n, 100.0)
    close[200:300] = np.linspace(100, 80, 100)
    close[300:450] = 75.0

    high = close + 1.0
    low = close - 0.5
    opens = close + 0.2
    volume = np.full(n, 1000.0)
    volume[300:450] = 5000.0

    return pd.DataFrame(
        {
            "open": opens,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=dates,
    )


class TestKeltnerBreakoutADX:
    """Tests for the KeltnerBreakoutADX strategy."""

    def test_default_params_instantiation(self):
        """Strategy can be instantiated with default parameters."""
        s = KeltnerBreakoutADX()
        assert s.name == "KeltnerBreakoutADX"
        assert s.timeframe == "1h"
        assert s.min_bars == 100
        assert s.version == "1.0.0"
        assert s.params["kc_period"] == 20
        assert s.params["kc_multiplier"] == 2.0
        assert s.params["atr_period"] == 14
        assert s.params["adx_period"] == 14
        assert s.params["adx_threshold"] == 22
        assert s.params["vol_period"] == 20
        assert s.params["vol_threshold"] == 1.2
        assert s.params["stop_atr_mult"] == 2.5

    def test_custom_params_instantiation(self):
        """Strategy can be instantiated with custom parameters."""
        s = KeltnerBreakoutADX(
            params={"kc_period": 10, "adx_threshold": 25, "vol_threshold": 1.5}
        )
        assert s.params["kc_period"] == 10
        assert s.params["adx_threshold"] == 25
        assert s.params["vol_threshold"] == 1.5
        # Unchanged defaults
        assert s.params["atr_period"] == 14
        assert s.params["kc_multiplier"] == 2.0

    def test_generate_signal_returns_correct_shape(self):
        """generate_signal() returns Series with correct shape and types."""
        df = _make_flat_df(500)
        s = KeltnerBreakoutADX()
        signal = s.generate_signal(df)

        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert (signal.index == df.index).all()
        assert signal.dtype == int

    def test_signal_values_valid(self):
        """Signal values are only -1, 0, 1."""
        df = _make_uptrend_df(500)
        s = KeltnerBreakoutADX()
        signal = s.generate_signal(df)
        unique_vals = set(signal.unique())
        assert unique_vals.issubset({-1, 0, 1})

    def test_insufficient_bars_raises(self):
        """Short DataFrame raises StrategyError via preprocess."""
        df = _make_flat_df(50)  # fewer than min_bars=100
        s = KeltnerBreakoutADX()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_missing_columns_raises(self):
        """DataFrame missing required columns raises StrategyError."""
        df = pd.DataFrame(
            {"close": [100.0] * 500},
            index=pd.date_range("2024-01-01", periods=500, freq="1h"),
        )
        s = KeltnerBreakoutADX()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_uptrend_can_produce_long_signal(self):
        """In a strong uptrend with expansion, strategy may produce long signals."""
        df = _make_uptrend_df(500)
        s = KeltnerBreakoutADX()
        signal = s.generate_signal(df)
        assert (signal == 1).any() or (signal != 0).any()

    def test_downtrend_can_produce_short_signal(self):
        """In a strong downtrend with expansion, strategy may produce short signals."""
        df = _make_downtrend_df(500)
        s = KeltnerBreakoutADX()
        signal = s.generate_signal(df)
        assert (signal == -1).any() or (signal != 0).any()
