"""Tests for RegimeSwitch strategy."""

import numpy as np
import pandas as pd
import pytest

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.regime_switch import RegimeSwitch


class DummyStrategy(Strategy):
    def __init__(self, signal_value: int = 0, name: str = "Dummy"):
        self._signal_value = signal_value
        self._name = name
        super().__init__()

    @property
    def name(self) -> str:
        return self._name

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        return pd.Series(self._signal_value, index=df.index, dtype=int)


def _make_regime_df(n=300, trend="up", volatility="low"):
    """Generate synthetic OHLCV for regime testing."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    np.random.seed(42)
    if trend == "up":
        close = np.linspace(100, 200, n) + np.random.randn(n) * 0.5
    elif trend == "down":
        close = np.linspace(200, 100, n) + np.random.randn(n) * 0.5
    else:
        close = np.full(n, 100.0) + np.random.randn(n) * 0.5

    if volatility == "high":
        noise = np.random.randn(n) * 5.0
    elif volatility == "medium":
        noise = np.random.randn(n) * 1.0
    else:
        noise = np.random.randn(n) * 0.1

    close = close + noise
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


class TestRegimeSwitch:
    def test_delegates_to_trending_bull(self):
        df = _make_regime_df(n=300, trend="up", volatility="low")
        bull = DummyStrategy(signal_value=1, name="Bull")
        switch = RegimeSwitch(
            regime_map={"trending_bull": bull},
        )
        signal = switch.generate_signal(df)
        assert (signal == 1).sum() > 0

    def test_delegates_to_default(self):
        df = _make_regime_df(n=300, trend="flat", volatility="low")
        default = DummyStrategy(signal_value=1, name="Default")
        switch = RegimeSwitch(
            regime_map={"trending_bull": DummyStrategy(signal_value=0, name="Bull")},
            default=default,
        )
        signal = switch.generate_signal(df)
        assert (signal == 1).sum() > 0

    def test_returns_zero_when_no_match(self):
        df = _make_regime_df(n=300, trend="flat", volatility="low")
        switch = RegimeSwitch(
            regime_map={"trending_bull": DummyStrategy(signal_value=1, name="Bull")},
        )
        signal = switch.generate_signal(df)
        assert (signal == 0).all()

    def test_min_bars_is_max_of_strategies(self):
        s1 = DummyStrategy(name="S1")
        s1.min_bars = 100
        s2 = DummyStrategy(name="S2")
        s2.min_bars = 200
        switch = RegimeSwitch(regime_map={"a": s1, "b": s2})
        assert switch.min_bars == 200

    def test_timeframe_from_first_strategy(self):
        s1 = DummyStrategy(name="S1")
        s1.timeframe = "4h"
        switch = RegimeSwitch(regime_map={"a": s1})
        assert switch.timeframe == "4h"

    def test_name_contains_regimes(self):
        switch = RegimeSwitch(
            regime_map={
                "trending_bull": DummyStrategy(name="Bull"),
                "volatile": DummyStrategy(name="Vol"),
            }
        )
        assert "trending_bull" in switch.name
        assert "volatile" in switch.name

    def test_preprocessing_enforced(self):
        df = pd.DataFrame({"close": [1, 2, 3]})
        switch = RegimeSwitch(
            regime_map={"trending_bull": DummyStrategy(signal_value=1, name="Bull")},
        )
        with pytest.raises(Exception):
            switch.generate_signal(df)
