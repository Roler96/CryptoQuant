"""Tests for ATRBreakoutTrend strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from strategies.atr_breakout_trend import ATRBreakoutTrend


def _make_flat_df(n: int = 500) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n, freq="5min")
    close = np.full(n, 100.0)
    return pd.DataFrame(
        {"open": close - 0.1, "high": close + 0.5, "low": close - 0.5,
         "close": close, "volume": np.full(n, 1000.0)},
        index=dates,
    )


def _make_breakout_df(n: int = 500, direction: str = "up") -> pd.DataFrame:
    """Generate data that triggers a breakout entry.

    Strategy: create a sustained uptrend/downtrend with a volatility
    expansion spike that pushes price beyond the rolling channel AND
    above/below the EMA. Use narrow ranges for most bars and a sudden
    wide bar to satisfy the ATR expansion condition.
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="5min")
    rng = np.random.RandomState(42)

    if direction == "up":
        # Build a gradual uptrend so EMA rises slowly
        close = np.linspace(100, 130, n)
    else:
        close = np.linspace(100, 70, n)

    # Tiny noise — keep bars narrow so channel_high ≈ recent highs
    noise = rng.randn(n) * 0.1
    close = close + noise

    # Narrow bars everywhere except breakout region
    high = close + np.abs(rng.randn(n) * 0.3)
    low = close - np.abs(rng.randn(n) * 0.3)

    if direction == "up":
        # Bar near the end: spike high above channel, wide range for ATR expansion
        breakout_idx = n - 100
        high[breakout_idx] = close[breakout_idx] + 20.0  # way above channel_high
        low[breakout_idx] = close[breakout_idx] - 10.0   # wide range > ATR
    else:
        breakout_idx = n - 100
        low[breakout_idx] = close[breakout_idx] - 20.0   # way below channel_low
        high[breakout_idx] = close[breakout_idx] + 10.0  # wide range > ATR

    return pd.DataFrame(
        {"open": close + rng.randn(n) * 0.2,
         "high": high, "low": low,
         "close": close, "volume": np.full(n, 1000.0)},
        index=dates,
    )


class TestATRBreakoutTrend:
    def test_default_params(self):
        s = ATRBreakoutTrend()
        assert s.name == "ATRBreakoutTrend"
        assert s.timeframe == "5m"
        assert s.min_bars == 200
        assert s.params["channel_period"] == 20
        assert s.params["atr_period"] == 14
        assert s.params["expansion_mult"] == 1.5
        assert s.params["trend_ema"] == 200

    def test_custom_params(self):
        s = ATRBreakoutTrend(params={"trend_ema": 50, "expansion_mult": 2.0})
        assert s.params["trend_ema"] == 50
        assert s.params["expansion_mult"] == 2.0
        assert s.params["channel_period"] == 20

    def test_signal_shape_and_type(self):
        df = _make_breakout_df(500, "up")
        s = ATRBreakoutTrend()
        signal = s.generate_signal(df)
        assert isinstance(signal, pd.Series)
        assert len(signal) == 500
        assert signal.dtype == int

    def test_signal_values_valid(self):
        df = _make_breakout_df(500, "up")
        s = ATRBreakoutTrend()
        signal = s.generate_signal(df)
        assert set(signal.unique()).issubset({-1, 0, 1})

    def test_insufficient_bars_raises(self):
        df = _make_flat_df(50)
        s = ATRBreakoutTrend()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_missing_columns_raises(self):
        df = pd.DataFrame(
            {"close": [100.0] * 500},
            index=pd.date_range("2024-01-01", periods=500, freq="5min"),
        )
        s = ATRBreakoutTrend()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_uptrend_produces_long_signal(self):
        """Sustained uptrend with breakout spike should produce long entry."""
        df = _make_breakout_df(600, "up")
        s = ATRBreakoutTrend(params={"trend_ema": 20, "expansion_mult": 0.5})
        signal = s.generate_signal(df)
        assert (signal == 1).any(), f"No long signal. Values: {signal.value_counts().to_dict()}"

    def test_downtrend_produces_short_signal(self):
        """Sustained downtrend with breakdown spike should produce short entry."""
        df = _make_breakout_df(600, "down")
        s = ATRBreakoutTrend(params={"trend_ema": 20, "expansion_mult": 0.5})
        signal = s.generate_signal(df)
        assert (signal == -1).any(), f"No short signal. Values: {signal.value_counts().to_dict()}"

    def test_trend_filter_blocks_counter_trend_long(self):
        """Long entry blocked when price below EMA (downtrend with breakout)."""
        # Build a downtrend — price goes from 100 to 70 over 600 bars.
        # EMA(300) stays far above price, blocking all long entries.
        df = _make_breakout_df(600, "down")
        # Override the breakout to be upward but price still below EMA
        df["high"].iloc[-100] = df["close"].iloc[-100] + 20.0
        df["low"].iloc[-100] = df["close"].iloc[-100] - 10.0
        s = ATRBreakoutTrend(params={"trend_ema": 300, "expansion_mult": 0.5})
        signal = s.generate_signal(df)
        assert not (signal == 1).any(), (
            f"Long signal should be blocked by trend filter in downtrend. "
            f"Signals: {signal.value_counts().to_dict()}"
        )

    def test_flat_market_few_signals(self):
        """Flat market should not produce excessive signals."""
        df = _make_flat_df(500)
        s = ATRBreakoutTrend()
        signal = s.generate_signal(df)
        changes = (signal.diff() != 0).sum()
        assert changes < 20, f"Too many signal transitions: {changes}"

    def test_expansion_mult_controls_sensitivity(self):
        """Higher expansion_mult = fewer entries (more selective)."""
        df = _make_breakout_df(600, "up")
        s_low = ATRBreakoutTrend(params={"expansion_mult": 0.5, "trend_ema": 20})
        s_high = ATRBreakoutTrend(params={"expansion_mult": 3.0, "trend_ema": 20})
        sig_low = s_low.generate_signal(df)
        sig_high = s_high.generate_signal(df)
        changes_low = (sig_low.diff() != 0).sum()
        changes_high = (sig_high.diff() != 0).sum()
        assert changes_low >= changes_high, (
            f"Higher expansion should not produce more signals. "
            f"Low={changes_low}, High={changes_high}"
        )
