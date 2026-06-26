"""Tests for DualThrustBreakout strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_dual_thrust_breakout import DualThrustBreakout


def _make_flat_df(n: int = 500) -> pd.DataFrame:
    """Create a flat-price OHLCV DataFrame for testing."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = np.full(n, 100.0)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


def _make_breakout_long_df(n: int = 500) -> pd.DataFrame:
    """Create data with a clear breakout: flat then sudden spike."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = np.full(n, 100.0)
    high = np.full(n, 101.0)
    low = np.full(n, 99.0)

    # Insert a sharp spike at bar 350 that breaks above the bound
    # After 300 bars of flat data, range ≈ 2.0, bound = open + 0.3*2 = open+0.6
    # At bar 350: open ≈ 100, let close spike to 105
    close[350] = 105.0
    high[350] = 106.0
    low[350] = 99.0

    return pd.DataFrame(
        {
            "open": np.full(n, 100.0),
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


def _make_breakout_short_df(n: int = 500) -> pd.DataFrame:
    """Create data with a clear short breakout: flat then sudden drop."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = np.full(n, 200.0)
    high = np.full(n, 201.0)
    low = np.full(n, 199.0)

    # Insert a sharp drop at bar 350
    close[350] = 195.0
    high[350] = 201.0
    low[350] = 194.0

    return pd.DataFrame(
        {
            "open": np.full(n, 200.0),
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


class TestDualThrustBreakout:
    """Tests for the DualThrustBreakout strategy."""

    def test_default_params_instantiation(self):
        """Strategy can be instantiated with default parameters."""
        s = DualThrustBreakout()
        assert s.name == "DualThrustBreakout"
        assert s.timeframe == "1h"
        assert s.min_bars == 300
        assert s.version == "1.0.0"
        assert s.params["lookback"] == 20
        assert s.params["k1"] == 0.3
        assert s.params["k2"] == 0.3
        assert s.params["trend_period"] == 200

    def test_custom_params_instantiation(self):
        """Strategy can be instantiated with custom parameters."""
        s = DualThrustBreakout(
            params={"lookback": 14, "k1": 0.7, "k2": 0.3, "trend_period": 100}
        )
        assert s.params["lookback"] == 14
        assert s.params["k1"] == 0.7
        assert s.params["k2"] == 0.3
        assert s.params["trend_period"] == 100

    def test_signal_output_shape(self):
        """Signal output has same length and index as input DataFrame."""
        df = _make_flat_df(500)
        s = DualThrustBreakout()
        signal = s.generate_signal(df)
        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert signal.index.equals(df.index)
        assert signal.dtype == int

    def test_signal_values_valid(self):
        """All signal values are in {1, 0, -1}."""
        df = _make_flat_df(500)
        s = DualThrustBreakout()
        signal = s.generate_signal(df)
        assert signal.isin([1, 0, -1]).all()

    def test_no_signal_on_flat_data(self):
        """Flat price data with tiny range produces zero signals."""
        df = _make_flat_df(500)
        s = DualThrustBreakout()
        signal = s.generate_signal(df)
        assert (signal == 0).all()

    def test_insufficient_bars_raises(self):
        """Strategy raises StrategyError when DataFrame is too short."""
        df = _make_flat_df(50)
        s = DualThrustBreakout()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_generates_long_on_breakout(self):
        """A sharp price spike above the bound triggers long entry."""
        df = _make_breakout_long_df(500)
        s = DualThrustBreakout()
        signal = s.generate_signal(df)
        # Bar 350 should be a long signal after the spike
        assert (signal == 1).any(), "Expected long signal on price spike"

    def test_generates_short_on_breakout(self):
        """A sharp price drop below the bound triggers short entry."""
        df = _make_breakout_short_df(500)
        s = DualThrustBreakout()
        signal = s.generate_signal(df)
        assert (signal == -1).any(), "Expected short signal on price drop"

    def test_no_position_overlap(self):
        """Long and short signals never occur on the same bar."""
        df = _make_breakout_long_df(500)
        s = DualThrustBreakout()
        signal = s.generate_signal(df)
        long_bars = signal == 1
        short_bars = signal == -1
        assert not (long_bars & short_bars).any()
