"""Tests for MamaFamaTrend strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_mama_fama_trend import MamaFamaTrend


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
    """Create a strong trending-up DataFrame with directional cycles.

    Clean linear uptrend with sinusoidal cycles superimposed,
    so the Hilbert Transform can measure phase changes and
    MAMA/FAMA can produce crossovers.
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)
    trend = np.linspace(100.0, 200.0, n)
    # Add sinusoidal cycle (period ~50 bars) so Hilbert detects phase
    cycle = 3.0 * np.sin(2 * np.pi * np.arange(n) / 50.0)
    noise = rng.normal(0, 1.0, n)
    close = trend + cycle + noise
    return pd.DataFrame(
        {
            "open": close - 0.5,
            "high": close + 1.5,
            "low": close - 1.5,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


def _make_downtrend_df(n: int = 500) -> pd.DataFrame:
    """Create a strong trending-down DataFrame with directional cycles."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)
    trend = np.linspace(200.0, 80.0, n)
    cycle = 3.0 * np.sin(2 * np.pi * np.arange(n) / 50.0)
    noise = rng.normal(0, 1.0, n)
    close = trend + cycle + noise
    return pd.DataFrame(
        {
            "open": close + 0.5,
            "high": close + 1.5,
            "low": close - 1.5,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


class TestMamaFamaTrend:
    """Tests for the MamaFamaTrend strategy."""

    def test_default_params_instantiation(self):
        """Strategy can be instantiated with default parameters."""
        s = MamaFamaTrend()
        assert s.name == "MamaFamaTrend"
        assert s.timeframe == "1h"
        assert s.params["fast_limit"] == 0.5
        assert s.params["slow_limit"] == 0.05
        assert s.params["trend_period"] == 200

    def test_min_bars_raises(self):
        """Strategy raises StrategyError when df has fewer than min_bars."""
        s = MamaFamaTrend()
        dates = pd.date_range("2024-01-01", periods=50, freq="1h")
        df = pd.DataFrame(
            {
                "open": 100.0, "high": 101.0, "low": 99.0,
                "close": 100.0, "volume": 1000.0,
            },
            index=dates,
        )
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_signal_shape(self):
        """Signal output matches input DataFrame shape."""
        df = _make_uptrend_df(500)
        s = MamaFamaTrend()
        sig = s.generate_signal(df)
        assert len(sig) == len(df)
        assert sig.index.equals(df.index)
        assert sig.dtype in (int, np.int32, np.int64)

    def test_flat_market_no_trades(self):
        """In a completely flat market, MAMA/FAMA converge — minimal signals."""
        df = _make_flat_df(500)
        s = MamaFamaTrend()
        sig = s.generate_signal(df)
        # Flat market should produce very few signals
        assert (sig != 0).sum() < len(sig) * 0.15  # <15% non-flat

    def test_uptrend_generates_long_trades(self):
        """Strong uptrend with cycles produces MAMA/FAMA crosses → long entry."""
        df = _make_uptrend_df(500)
        s = MamaFamaTrend()
        sig = s.generate_signal(df)
        assert 1 in sig.values
        long_count = (sig == 1).sum()
        assert long_count > 0

    def test_downtrend_generates_short_trades(self):
        """Strong downtrend with cycles produces MAMA/FAMA crosses → short."""
        df = _make_downtrend_df(500)
        s = MamaFamaTrend()
        sig = s.generate_signal(df)
        assert -1 in sig.values
        short_count = (sig == -1).sum()
        assert short_count > 0

    def test_hilbert_transform_output(self):
        """Hilbert Transform produces valid phase values."""
        from cryptoquant.strategy.signals import hilbert_transform
        df = _make_uptrend_df(1000)
        ht = hilbert_transform(df)
        phase = ht["phase"].dropna()
        assert len(phase) > 0
        assert (phase >= 0.0).all()
        assert (phase <= 360.0).all()
        # delta_phase should be clamped at minimum 1
        dp = ht["delta_phase"].dropna()
        assert (dp >= 1.0).all()
