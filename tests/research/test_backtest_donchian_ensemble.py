"""Tests for DonchianEnsemble strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_donchian_ensemble import DonchianEnsemble


def _make_flat_df(n: int = 1500) -> pd.DataFrame:
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


def _make_uptrend_df(n: int = 1500) -> pd.DataFrame:
    """Create an OHLCV DataFrame with a clear Donchian breakout.

    Flat price around 100, then a sharp spike to 200, then settles.
    This ensures close clearly exceeds the rolling highest high.
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = np.full(n, 100.0)
    # Sharp single-bar breakout at bar 500
    breakout_bar = 500
    close[breakout_bar] = 200.0
    # Settle back slightly but stay elevated
    close[breakout_bar + 1 :] = 140.0

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


class TestDonchianEnsemble:
    """Tests for the DonchianEnsemble strategy."""

    def test_default_params_instantiation(self):
        """Strategy can be instantiated with default parameters."""
        s = DonchianEnsemble()
        assert s.name == "DonchianEnsemble"
        assert s.timeframe == "1h"
        assert s.min_bars == 1440
        assert s.version == "1.0.0"
        assert s.params["lookbacks"] == [12, 24, 48, 96, 168, 336, 720]
        assert s.params["vote_threshold"] == 0.5

    def test_custom_params_instantiation(self):
        """Strategy can be instantiated with custom parameters."""
        s = DonchianEnsemble(
            params={"lookbacks": [10, 20], "vote_threshold": 0.6}
        )
        assert s.params["lookbacks"] == [10, 20]
        assert s.params["vote_threshold"] == 0.6

    def test_generate_signal_returns_correct_shape(self):
        """generate_signal() returns Series with correct shape and types."""
        df = _make_flat_df(1500)
        s = DonchianEnsemble()
        signal = s.generate_signal(df)

        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert (signal.index == df.index).all()
        assert signal.dtype == int
        # In flat market, all signals should be 0
        assert all(v in (0, 1) for v in signal.unique())

    def test_signal_only_zero_and_one(self):
        """Signal values are only 0 (flat) or 1 (long), no shorts."""
        df = _make_uptrend_df(2000)
        s = DonchianEnsemble(
            params={"lookbacks": [10, 20], "vote_threshold": 0.5}
        )
        signal = s.generate_signal(df)
        unique_vals = set(signal.unique())
        assert unique_vals.issubset({0, 1})

    def test_insufficient_bars_raises(self):
        """Empty/short DataFrame raises StrategyError via preprocess."""
        df = _make_flat_df(100)  # fewer than min_bars=1440
        s = DonchianEnsemble()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_missing_columns_raises(self):
        """DataFrame missing required columns raises StrategyError."""
        df = pd.DataFrame(
            {"close": [100.0] * 1500},
            index=pd.date_range("2024-01-01", periods=1500, freq="1h"),
        )
        s = DonchianEnsemble()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_empty_lookbacks_returns_flat(self):
        """Empty lookbacks list produces all-flat signal."""
        df = _make_flat_df(1500)
        s = DonchianEnsemble(params={"lookbacks": []})
        signal = s.generate_signal(df)
        assert (signal == 0).all()

    def test_uptrend_produces_long_signal(self):
        """In a strong uptrend, the ensemble should eventually go long."""
        df = _make_uptrend_df(2000)
        s = DonchianEnsemble(params={"lookbacks": [10, 20], "vote_threshold": 0.5})
        signal = s.generate_signal(df)
        # At least some bars should be long in a strong uptrend
        assert signal.sum() > 0
