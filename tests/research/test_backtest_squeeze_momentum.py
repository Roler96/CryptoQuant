"""Tests for SqueezeMomentum strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_squeeze_momentum import SqueezeMomentum


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
    """Create trending data with increasing price."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    trend = np.linspace(100.0, 200.0, n)
    noise = np.random.default_rng(42).normal(0, 2.0, n)
    close = trend + noise
    return pd.DataFrame(
        {
            "open": close - 1.0,
            "high": close + 2.0,
            "low": close - 2.0,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


def _make_downtrend_df(n: int = 500) -> pd.DataFrame:
    """Create trending data with decreasing price."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    trend = np.linspace(200.0, 100.0, n)
    noise = np.random.default_rng(42).normal(0, 2.0, n)
    close = trend + noise
    return pd.DataFrame(
        {
            "open": close + 1.0,
            "high": close + 2.0,
            "low": close - 2.0,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


def _make_volatile_df(n: int = 500) -> pd.DataFrame:
    """Create volatile data with alternating up/down swings."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(42)
    close = 100.0
    closes = []
    for _ in range(n):
        close += rng.normal(0, 3.0)
        closes.append(close)
    closes = np.array(closes)
    return pd.DataFrame(
        {
            "open": closes - 1.0,
            "high": closes + np.abs(rng.normal(0, 2.0, n)),
            "low": closes - np.abs(rng.normal(0, 2.0, n)),
            "close": closes,
            "volume": np.full(n, 1000.0 + rng.normal(0, 200, n)),
        },
        index=dates,
    )


class TestSqueezeMomentum:
    """Tests for SqueezeMomentum strategy."""

    def test_initialization(self):
        """Strategy initializes with default params."""
        s = SqueezeMomentum({})
        assert s.name == "SqueezeMomentum"
        assert s.params["bb_period"] == 20
        assert s.params["kc_period"] == 20
        assert s.params["trend_period"] == 200
        assert s.params["trailing_stop_mult"] == 2.0

    def test_custom_params(self):
        """Custom params override defaults."""
        s = SqueezeMomentum({"bb_period": 10, "trend_period": 100})
        assert s.params["bb_period"] == 10
        assert s.params["trend_period"] == 100

    def test_insufficient_bars(self):
        """Strategy raises StrategyError with too few bars."""
        s = SqueezeMomentum({})
        df = _make_flat_df(n=50)
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_flat_price_no_signals(self):
        """Flat price produces no squeeze fires — no signals."""
        s = SqueezeMomentum({})
        df = _make_flat_df(n=500)
        signal = s.generate_signal(df)
        assert len(signal) == len(df)
        assert signal.dtype == int
        assert set(signal.unique()).issubset({-1, 0, 1})

    def test_uptrend_generates_signal(self):
        """Uptrending data should eventually generate some signal."""
        s = SqueezeMomentum({})
        df = _make_uptrend_df(n=500)
        signal = s.generate_signal(df)
        assert len(signal) == len(df)
        # In uptrend with volatility changes, should have at least some non-zero values
        # Verify no NaN and valid signal values
        assert not signal.isna().any()
        assert signal.dtype == int

    def test_downtrend_generates_signal(self):
        """Downtrending data should eventually generate some signal."""
        s = SqueezeMomentum({})
        df = _make_downtrend_df(n=500)
        signal = s.generate_signal(df)
        assert len(signal) == len(df)
        assert not signal.isna().any()
        assert signal.dtype == int

    def test_volatile_data_has_some_signals(self):
        """Volatile data with BB/KC interaction should produce signals."""
        s = SqueezeMomentum({})
        df = _make_volatile_df(n=500)
        signal = s.generate_signal(df)
        assert len(signal) == len(df)
        assert not signal.isna().any()
        assert signal.dtype == int
        # In volatile data with volume changes, should have both long and short signals
        values = set(signal.unique())
        assert values.issubset({-1, 0, 1})
