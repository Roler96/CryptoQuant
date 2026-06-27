"""Tests for BBSqueezeBreakout strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_bb_squeeze_breakout import BBSqueezeBreakout


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


def _make_expanding_range_df(n: int = 600) -> pd.DataFrame:
    """Create data with a clear squeeze followed by breakout.

    First 200 bars: tight consolidation (squeeze).
    Next 50 bars: sharp breakout up.
    Rest: continuation with noise.
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)

    close = np.full(n, 100.0)
    high = np.full(n, 100.0)
    low = np.full(n, 100.0)

    # Phase 1: Tight consolidation (squeeze) — bars 0-199
    base = 100.0
    for i in range(200):
        base += rng.normal(0, 0.1)
        close[i] = base
        high[i] = base + 0.15
        low[i] = base - 0.15

    # Phase 2: Sharp breakout up — bars 200-249
    for i in range(200, 250):
        base += 1.5 + abs(rng.normal(0, 0.5))
        close[i] = base
        high[i] = base + 1.0 + abs(rng.normal(0, 0.3))
        low[i] = base - 0.5

    # Phase 3: Continuation — bars 250+
    for i in range(250, n):
        base += rng.normal(0.1, 2.0)
        close[i] = base
        high[i] = base + abs(rng.normal(0, 1.5))
        low[i] = base - abs(rng.normal(0, 1.5))

    return pd.DataFrame(
        {
            "open": close - 0.2,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


class TestBBSqueezeBreakout:
    """Tests for the BBSqueezeBreakout strategy."""

    def test_default_params_instantiation(self):
        """Strategy can be instantiated with default parameters."""
        s = BBSqueezeBreakout()
        assert s.name == "BBSqueezeBreakout"
        assert s.timeframe == "1h"
        assert s.min_bars == 300
        assert s.version == "1.0.0"
        assert s.params["bb_period"] == 20
        assert s.params["bb_std"] == 2.0
        assert s.params["squeeze_lookback"] == 125

    def test_custom_params_instantiation(self):
        """Strategy can be instantiated with custom parameters."""
        s = BBSqueezeBreakout(
            params={"bb_period": 10, "bb_std": 1.5, "squeeze_lookback": 50}
        )
        assert s.params["bb_period"] == 10
        assert s.params["bb_std"] == 1.5
        assert s.params["squeeze_lookback"] == 50

    def test_generate_signal_returns_correct_shape(self):
        """generate_signal() returns Series with correct shape and types."""
        df = _make_flat_df(500)
        s = BBSqueezeBreakout(params={"squeeze_lookback": 50})
        signal = s.generate_signal(df)

        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert (signal.index == df.index).all()
        assert signal.dtype == int

    def test_signal_values_valid(self):
        """Signal values are only -1, 0, 1."""
        df = _make_expanding_range_df(500)
        s = BBSqueezeBreakout(params={"squeeze_lookback": 50})
        signal = s.generate_signal(df)
        unique_vals = set(signal.unique())
        assert unique_vals.issubset({-1, 0, 1})

    def test_insufficient_bars_raises(self):
        """Short DataFrame raises StrategyError via preprocess."""
        df = _make_flat_df(200)
        s = BBSqueezeBreakout()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_missing_columns_raises(self):
        """DataFrame missing required columns raises StrategyError."""
        df = pd.DataFrame(
            {"close": [100.0] * 500},
            index=pd.date_range("2024-01-01", periods=500, freq="1h"),
        )
        s = BBSqueezeBreakout()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_expanding_range_runs_without_error(self):
        """Strategy runs on expanding range data without error."""
        df = _make_expanding_range_df(600)
        s = BBSqueezeBreakout(params={"squeeze_lookback": 50})
        signal = s.generate_signal(df)
        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert signal.dtype == int
        unique_vals = set(signal.unique())
        assert unique_vals.issubset({-1, 0, 1})
