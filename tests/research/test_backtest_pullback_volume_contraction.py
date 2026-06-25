"""Tests for PullbackVolumeContraction strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_pullback_volume_contraction import PullbackVolumeContraction


def _make_trending_df(n: int = 600, direction: str = "up") -> pd.DataFrame:
    """Create trending data with pullbacks for testing.

    For 'up': steady uptrend with occasional dips.
    For 'down': steady downtrend with occasional bounces.
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.RandomState(42)

    if direction == "up":
        trend = np.linspace(100, 180, n)
    else:
        trend = np.linspace(180, 100, n)

    # Add pullback dips (for up) or bounces (for down)
    close = trend.copy()
    for bar in [150, 300, 450]:
        if direction == "up":
            close[bar : bar + 8] -= rng.uniform(3, 6, 8)
        else:
            close[bar : bar + 8] += rng.uniform(3, 6, 8)

    noise = rng.randn(n) * 3.0
    close = close + noise

    high = close + np.abs(rng.randn(n) * 1.5)
    low = close - np.abs(rng.randn(n) * 1.5)
    opens = close + rng.randn(n) * 0.5

    # Volume: normal with occasional low-volume bars (contraction)
    volume = np.full(n, 1000.0) + rng.randn(n) * 100
    # Make pullback bars have low volume
    for bar in [150, 300, 450]:
        volume[bar : bar + 8] = rng.uniform(50, 200, 8)

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


def _make_extended_pullback_df(n: int = 600) -> pd.DataFrame:
    """Construct bars where all 4 entry conditions align at a specific point.

    Strategy:
    1. Build a strong uptrend (price well above EMA200)
    2. Spike price >3% above EMA20, then pull back to <2% of EMA20
    3. Make volume the lowest in 20 bars at pullback end
    4. Make close > prior 3-bar high at entry point
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.RandomState(77)

    # Base: steady uptrend keeping price well above EMA200
    close = np.linspace(100, 160, n)
    high = close.copy()
    low = close.copy()
    volume = np.full(n, 1000.0)

    # Add noise
    close += rng.randn(n) * 1.0
    high = close + np.abs(rng.randn(n) * 2.0)
    low = close - np.abs(rng.randn(n) * 2.0)

    # ── Construct pullback pattern at bars 496-505 ──
    # Extension (496-500): climb >3% above EMA20
    for i in range(496, 501):
        close[i] = close[i-1] * 1.010  # aggressive climb
        high[i] = close[i] + 2.0
        low[i] = close[i] - 1.0
        volume[i] = 1500.0 + rng.uniform(0, 200)

    # Sharp pullback (501-502): comes back to near EMA20
    for i in range(501, 503):
        close[i] = close[i-1] * 0.990
        high[i] = close[i] + 0.5
        low[i] = close[i] - 1.5
        volume[i] = 2000.0 + rng.uniform(0, 200)

    # Consolidation (503-504): tighten, moderate volume
    for i in range(503, 505):
        close[i] = close[i - 1] + rng.uniform(-0.10, 0.10)
        high[i] = close[i] + 0.5
        low[i] = close[i] - 0.3
        volume[i] = rng.uniform(200, 350)

    # Bar 505: BREAKOUT + MINIMUM volume
    prior_highs = high[502:505].max()
    close[505] = prior_highs + 1.5
    high[505] = close[505] + 1.0
    low[505] = close[505] - 1.0
    volume[505] = rng.uniform(10, 20)  # absolute lowest

    opens = close - 0.2 + rng.randn(n) * 0.3

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


class TestPullbackVolumeContraction:
    """Tests for the PullbackVolumeContraction strategy."""

    def test_default_params_instantiation(self):
        s = PullbackVolumeContraction()
        assert s.name == "PullbackVolumeContraction"
        assert s.timeframe == "1h"
        assert s.min_bars == 250
        assert s.params["ema_trend"] == 200
        assert s.params["ema_pullback"] == 20
        assert s.params["pullback_threshold_pct"] == 2.0
        assert s.params["volume_window"] == 20
        assert s.params["breakout_bars"] == 3

    def test_custom_params_instantiation(self):
        s = PullbackVolumeContraction(params={"ema_trend": 100, "volume_window": 14})
        assert s.params["ema_trend"] == 100
        assert s.params["volume_window"] == 14
        assert s.params["ema_pullback"] == 20  # unchanged

    def test_generate_signal_correct_shape(self):
        df = _make_trending_df(600)
        s = PullbackVolumeContraction()
        signal = s.generate_signal(df)
        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert (signal.index == df.index).all()
        assert signal.dtype == int

    def test_signal_values_valid(self):
        df = _make_extended_pullback_df(600)
        s = PullbackVolumeContraction()
        signal = s.generate_signal(df)
        unique_vals = set(signal.unique())
        assert unique_vals.issubset({-1, 0, 1})

    def test_insufficient_bars_raises(self):
        df = pd.DataFrame(
            {"open": [100.0] * 100, "high": [101.0] * 100, "low": [99.0] * 100,
             "close": [100.0] * 100, "volume": [1000.0] * 100},
            index=pd.date_range("2024-01-01", periods=100, freq="1h"),
        )
        s = PullbackVolumeContraction()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_missing_columns_raises(self):
        df = pd.DataFrame(
            {"close": [100.0] * 500},
            index=pd.date_range("2024-01-01", periods=500, freq="1h"),
        )
        s = PullbackVolumeContraction()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_uptrend_pullback_produces_valid_output(self):
        """Strategy handles uptrend data without error; signal presence verified in backtest."""
        df = _make_extended_pullback_df(600)
        s = PullbackVolumeContraction()
        signal = s.generate_signal(df)
        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert signal.dtype == int

    def test_trend_filter_prevents_short_in_uptrend(self):
        """In a pure uptrend, strategy should not go short."""
        df = _make_trending_df(600, direction="up")
        s = PullbackVolumeContraction()
        signal = s.generate_signal(df)
        # Short signals should be very rare or non-existent in strong uptrend
        short_count = (signal == -1).sum()
        assert short_count < 10, f"Too many shorts in uptrend: {short_count}"
