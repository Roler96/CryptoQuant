"""Tests for VIDYACrossoverExpansion strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from cryptoquant.strategy.signals import vidya
from research.backtest_vidya_crossover_expansion import VIDYACrossoverExpansion


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
    """Create trending data with strong price rise and wide bars."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)
    trend = np.linspace(100.0, 300.0, n)
    noise = rng.normal(0, 1.0, n)
    close = trend + noise
    bar_range = np.where(np.arange(n) % 3 == 0, 8.0, 2.0)
    half_range = bar_range / 2
    return pd.DataFrame(
        {
            "open": close - half_range * 0.3,
            "high": close + half_range,
            "low": close - half_range,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


class TestVIDYACrossoverExpansion:
    """Tests for VIDYACrossoverExpansion strategy."""

    def test_initialization(self):
        """Strategy initializes with default params."""
        s = VIDYACrossoverExpansion({})
        assert s.name == "VIDYACrossoverExpansion"
        assert s.params["vidya_fast_period"] == 6
        assert s.params["vidya_slow_period"] == 24
        assert s.params["vidya_cmo_period"] == 9
        assert s.params["atr_percentile"] == 80

    def test_custom_params(self):
        """Custom params override defaults."""
        s = VIDYACrossoverExpansion({
            "vidya_fast_period": 5,
            "atr_percentile": 70,
        })
        assert s.params["vidya_fast_period"] == 5
        assert s.params["atr_percentile"] == 70
        assert s.params["vidya_slow_period"] == 24  # unchanged

    def test_insufficient_bars(self):
        """Strategy raises StrategyError with too few bars."""
        s = VIDYACrossoverExpansion({})
        df = _make_flat_df(n=50)
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_flat_price_signal_valid(self):
        """Flat price produces valid signal format."""
        s = VIDYACrossoverExpansion({})
        df = _make_flat_df(n=500)
        signal = s.generate_signal(df)
        assert len(signal) == len(df)
        assert signal.dtype == int
        assert set(signal.unique()).issubset({-1, 0, 1})

    def test_uptrend_generates_signal(self):
        """Uptrend should generate signals (long or flat)."""
        s = VIDYACrossoverExpansion({})
        df = _make_uptrend_df(n=500)
        signal = s.generate_signal(df)
        assert len(signal) == len(df)
        assert set(signal.unique()).issubset({-1, 0, 1})

    def test_vidya_indicator_computes(self):
        """VIDYA indicator produces valid output."""
        df = _make_uptrend_df(n=500)
        result = vidya(df["close"], vidya_period=6, cmo_period=9)
        assert len(result) == len(df)
        valid = result.dropna()
        assert len(valid) > 100  # VIDYA should be defined for most bars

    def test_vidya_tracks_price_direction(self):
        """VIDYA should roughly follow price direction in uptrend."""
        df = _make_uptrend_df(n=500)
        close = df["close"]
        result = vidya(close, vidya_period=6, cmo_period=9)
        # VIDYA should be higher at end than at start in uptrend
        mid = len(close) // 2
        assert result.iloc[mid:].mean() > result.iloc[:mid].mean()
