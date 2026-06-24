"""Tests for SupertrendRegime strategy."""

import numpy as np
import pandas as pd
import pytest

from research.backtest_supertrend_regime import SupertrendRegime
from cryptoquant.strategy.base import Strategy
from cryptoquant.exceptions import StrategyError


def _make_ohlcv_df(n_bars: int = 700, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic OHLCV data with a gentle uptrend."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n_bars, freq="1h")

    # Gentle uptrend with noise
    trend = np.linspace(100, 130, n_bars)
    noise = rng.normal(0, 1.5, n_bars)
    close = trend + noise

    bar_range = rng.uniform(0.5, 2.0, n_bars)
    high = close + bar_range * 0.6
    low = close - bar_range * 0.4
    open_ = close - rng.uniform(-0.5, 0.5, n_bars)
    volume = rng.uniform(500, 2000, n_bars)

    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=dates,
    )


class TestSupertrendRegime:
    """Unit tests for SupertrendRegime strategy."""

    def test_instantiation(self):
        """Strategy instantiates with default params and inherits from Strategy."""
        strategy = SupertrendRegime()
        assert isinstance(strategy, Strategy)
        assert strategy.name == "SupertrendRegime"
        assert strategy.timeframe == "1h"
        assert strategy.min_bars == 600
        assert strategy.version == "1.0.0"
        assert strategy.params["atr_period"] == 10
        assert strategy.params["factor"] == 3.0
        assert strategy.params["adx_period"] == 14
        assert strategy.params["adx_threshold"] == 25
        assert strategy.params["regime_filter_enabled"] is True

    def test_instantiation_with_custom_params(self):
        """Strategy accepts custom params that override defaults."""
        strategy = SupertrendRegime(
            params={"atr_period": 14, "factor": 2.5, "regime_filter_enabled": False}
        )
        assert strategy.params["atr_period"] == 14
        assert strategy.params["factor"] == 2.5
        assert strategy.params["regime_filter_enabled"] is False
        # Unspecified params retain defaults
        assert strategy.params["adx_period"] == 14

    def test_signal_shape_and_index(self):
        """Signal has same length and index as input DataFrame."""
        df = _make_ohlcv_df(n_bars=700)
        strategy = SupertrendRegime()
        signal = strategy.generate_signal(df)

        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert signal.index.equals(df.index)

    def test_signal_values_are_valid(self):
        """Signal contains only 0 and 1 (long-only, no shorts)."""
        df = _make_ohlcv_df(n_bars=700)
        strategy = SupertrendRegime()
        signal = strategy.generate_signal(df)

        unique_vals = set(signal.unique())
        assert unique_vals.issubset({0, 1})

    def test_signal_with_filter_disabled(self):
        """With regime_filter_enabled=False and low factor, signal triggers."""
        df = _make_ohlcv_df(n_bars=700)
        strategy = SupertrendRegime(
            params={"regime_filter_enabled": False, "factor": 1.5}
        )
        signal = strategy.generate_signal(df)

        unique_vals = set(signal.unique())
        assert unique_vals.issubset({0, 1})
        # With factor=1.5 and rising data, should trigger some long signals
        assert (signal == 1).sum() > 0

    def test_empty_dataframe_raises(self):
        """StrategyError raised when DataFrame has insufficient bars."""
        df = _make_ohlcv_df(n_bars=50)  # Below min_bars=600
        strategy = SupertrendRegime()
        with pytest.raises(StrategyError):
            strategy.generate_signal(df)

    def test_missing_columns_raises(self):
        """StrategyError raised when DataFrame is missing required columns."""
        df = pd.DataFrame({"close": [100.0] * 700})
        strategy = SupertrendRegime()
        with pytest.raises(StrategyError):
            strategy.generate_signal(df)

    def test_repr(self):
        """__repr__ includes strategy name and params."""
        strategy = SupertrendRegime(params={"atr_period": 10, "factor": 3.0})
        r = repr(strategy)
        assert "SupertrendRegime" in r
        assert "atr_period=10" in r
        assert "factor=3.0" in r
