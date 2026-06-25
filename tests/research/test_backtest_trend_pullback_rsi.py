"""Tests for TrendPullbackRSI strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_trend_pullback_rsi import TrendPullbackRSI


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


def _make_uptrend_with_dip_df(n: int = 500) -> pd.DataFrame:
    """Create uptrend with a minor dip to create RSI pullback opportunity.

    Price rises slowly (uptrend above EMA200), then dips slightly
    to bring RSI into the 40-50 zone before resuming the uptrend.
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = np.full(n, 100.0, dtype=float)

    # Steady uptrend: price rises from 100 to 130 over 350 bars
    close[50:400] = np.linspace(100, 130, 350)

    # Create a minor pullback (dip) to trigger RSI 40-50
    dip_start, dip_end = 320, 345
    base_at_dip = close[dip_start]
    close[dip_start:dip_end] = np.linspace(base_at_dip, base_at_dip * 0.93, dip_end - dip_start)

    # Recovery
    close[dip_end:] = np.linspace(close[dip_end], 135, n - dip_end)

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


def _make_downtrend_with_bounce_df(n: int = 500) -> pd.DataFrame:
    """Create downtrend with a minor bounce for RSI 50-60 short entry.

    Price declines slowly (downtrend below EMA200), then bounces
    slightly to bring RSI into the 50-60 zone before resuming the decline.
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = np.full(n, 100.0, dtype=float)

    # Steady downtrend: price falls from 100 to 70 over 350 bars
    close[50:400] = np.linspace(100, 70, 350)

    # Create a minor bounce to trigger RSI 50-60
    bounce_start, bounce_end = 320, 345
    base_at_bounce = close[bounce_start]
    close[bounce_start:bounce_end] = np.linspace(base_at_bounce, base_at_bounce * 1.07, bounce_end - bounce_start)

    # Resume decline
    close[bounce_end:] = np.linspace(close[bounce_end], 65, n - bounce_end)

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


class TestTrendPullbackRSI:
    """Tests for the TrendPullbackRSI strategy."""

    def test_default_params_instantiation(self):
        """Strategy can be instantiated with default parameters."""
        s = TrendPullbackRSI()
        assert s.name == "TrendPullbackRSI"
        assert s.timeframe == "1h"
        assert s.min_bars == 250
        assert s.version == "1.0.0"
        assert s.params["ema_period"] == 200
        assert s.params["rsi_period"] == 14
        assert s.params["rsi_low"] == 40
        assert s.params["rsi_high"] == 50

    def test_custom_params_instantiation(self):
        """Strategy can be instantiated with custom parameters."""
        s = TrendPullbackRSI(
            params={"rsi_low": 35, "rsi_high": 45, "ema_period": 100}
        )
        assert s.params["rsi_low"] == 35
        assert s.params["rsi_high"] == 45
        assert s.params["ema_period"] == 100
        assert s.params["rsi_period"] == 14  # unchanged default

    def test_generate_signal_returns_correct_shape(self):
        """generate_signal() returns Series with correct shape and types."""
        df = _make_flat_df(500)
        s = TrendPullbackRSI()
        signal = s.generate_signal(df)

        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert (signal.index == df.index).all()
        assert signal.dtype == int

    def test_signal_values_valid(self):
        """Signal values are only -1, 0, 1."""
        df = _make_uptrend_with_dip_df(500)
        s = TrendPullbackRSI()
        signal = s.generate_signal(df)
        unique_vals = set(signal.unique())
        assert unique_vals.issubset({-1, 0, 1})

    def test_insufficient_bars_raises(self):
        """Short DataFrame raises StrategyError via preprocess."""
        df = _make_flat_df(100)  # fewer than min_bars=250
        s = TrendPullbackRSI()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_missing_columns_raises(self):
        """DataFrame missing required columns raises StrategyError."""
        df = pd.DataFrame(
            {"close": [100.0] * 500},
            index=pd.date_range("2024-01-01", periods=500, freq="1h"),
        )
        s = TrendPullbackRSI()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_flat_market_produces_no_signal(self):
        """Flat market (no trend, price around EMA) should produce no signals.

        In a flat market, RSI will hover near 50, and the RSI 40-50 zone
        requires a dip. Without a dip, no signal fires. Also, flat price
        means no clear trend for the EMA filter.
        """
        df = _make_flat_df(500)
        s = TrendPullbackRSI()
        signal = s.generate_signal(df)
        # In perfectly flat market, RSI stays near 50 and never dips
        assert (signal == 0).all()
