"""Tests for ZScoreMomentumTrend strategy."""

import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_zscore_momentum_trend import ZScoreMomentumTrend


def make_ohlcv(length: int = 500, trend: str = "up") -> pd.DataFrame:
    """Create synthetic OHLCV data with a known trend."""
    rng = np.random.default_rng(42)
    base = 50000.0
    drift = 50.0 if trend == "up" else -50.0 if trend == "down" else 0.0

    closes = []
    price = base
    for i in range(length):
        price += drift + rng.normal(0, 200)
        closes.append(max(price, 100))
    closes = np.array(closes)

    highs = closes + np.abs(rng.normal(0, 100, length))
    lows = closes - np.abs(rng.normal(0, 100, length))
    opens = closes + rng.normal(0, 50, length)
    volumes = rng.uniform(10, 100, length)

    return pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        },
        index=pd.date_range("2025-01-01", periods=length, freq="1h"),
    )


def test_zscore_momentum_returns_pandas_series():
    """Signal output should be a pandas Series of int."""
    df = make_ohlcv(500, "up")
    strategy = ZScoreMomentumTrend()
    signal = strategy.generate_signal(df)

    assert isinstance(signal, pd.Series)
    assert signal.dtype == int
    assert len(signal) == len(df)


def test_zscore_momentum_values_are_valid():
    """Signal should only contain -1, 0, or 1."""
    df = make_ohlcv(500, "up")
    strategy = ZScoreMomentumTrend()
    signal = strategy.generate_signal(df)

    valid = signal.isin([-1, 0, 1])
    assert valid.all(), f"Invalid signal values: {signal[~valid].unique()}"


def test_zscore_momentum_detects_uptrend():
    """Should produce at least some long signals in a strong uptrend."""
    # Use shorter long_period and more bars so Z-score can cross ±1.0
    df = make_ohlcv(1200, "up")
    strategy = ZScoreMomentumTrend(params={"long_period": 20, "short_period": 5,
                                            "entry_threshold": 0.5, "trend_period": 100})
    signal = strategy.generate_signal(df)

    long_count = (signal == 1).sum()
    assert long_count > 0, f"Expected at least some long signals in uptrend, got {long_count}"


def test_zscore_momentum_detects_downtrend():
    """Should produce at least some short signals in a strong downtrend."""
    df = make_ohlcv(1200, "down")
    strategy = ZScoreMomentumTrend(params={"long_period": 20, "short_period": 5,
                                            "entry_threshold": 0.5, "trend_period": 100})
    signal = strategy.generate_signal(df)

    short_count = (signal == -1).sum()
    assert short_count > 0, f"Expected at least some short signals in downtrend, got {short_count}"


def test_zscore_momentum_no_nan_in_output():
    """Output should not contain NaN values (only -1, 0, 1)."""
    df = make_ohlcv(600)
    strategy = ZScoreMomentumTrend()
    signal = strategy.generate_signal(df)

    assert not signal.isna().any(), "Signal should not contain NaN"


def test_zscore_momentum_min_bars_enforced():
    """Should raise if data is shorter than min_bars."""
    df = make_ohlcv(100, "up")
    strategy = ZScoreMomentumTrend()
    with pytest.raises(StrategyError):
        strategy.generate_signal(df)
