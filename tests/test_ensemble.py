"""Tests for StrategyEnsemble."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.ensemble import StrategyEnsemble


def _make_df(n=50, start_price=100.0):
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = np.full(n, start_price)
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


class AlwaysLong(Strategy):
    timeframe = "1h"
    min_bars = 1
    DEFAULT_PARAMS = {}

    @property
    def name(self) -> str:
        return "AlwaysLong"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        return pd.Series(1, index=df.index, dtype=int)


class AlwaysShort(Strategy):
    timeframe = "1h"
    min_bars = 1
    DEFAULT_PARAMS = {}

    @property
    def name(self) -> str:
        return "AlwaysShort"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        return pd.Series(-1, index=df.index, dtype=int)


class AlwaysFlat(Strategy):
    timeframe = "1h"
    min_bars = 1
    DEFAULT_PARAMS = {}

    @property
    def name(self) -> str:
        return "AlwaysFlat"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        return pd.Series(0, index=df.index, dtype=int)


class TestStrategyEnsemble:
    def test_weighted_avg_equal_weights(self):
        df = _make_df(10)
        ensemble = StrategyEnsemble(
            strategies=[AlwaysLong(), AlwaysShort()],
            weights=[1.0, 1.0],
            method="weighted_avg",
        )
        signal = ensemble.generate_signal(df)
        assert (signal == 0).all()

    def test_weighted_avg_skewed_weights(self):
        df = _make_df(10)
        ensemble = StrategyEnsemble(
            strategies=[AlwaysLong(), AlwaysShort()],
            weights=[4.0, 1.0],
            method="weighted_avg",
        )
        signal = ensemble.generate_signal(df)
        assert (signal == 1).all()

    def test_majority_vote_long_wins(self):
        df = _make_df(10)
        ensemble = StrategyEnsemble(
            strategies=[AlwaysLong(), AlwaysLong(), AlwaysShort()],
            method="majority_vote",
        )
        signal = ensemble.generate_signal(df)
        assert (signal == 1).all()

    def test_majority_vote_tie_to_zero(self):
        df = _make_df(10)
        ensemble = StrategyEnsemble(
            strategies=[AlwaysLong(), AlwaysShort()],
            method="majority_vote",
        )
        signal = ensemble.generate_signal(df)
        assert (signal == 0).all()

    def test_empty_strategies_raises(self):
        with pytest.raises(ValueError, match="strategies must not be empty"):
            StrategyEnsemble(strategies=[])

    def test_mismatched_weights_raises(self):
        with pytest.raises(ValueError, match="weights length must match"):
            StrategyEnsemble(
                strategies=[AlwaysLong(), AlwaysShort()],
                weights=[1.0],
            )

    def test_unknown_method_raises(self):
        df = _make_df(10)
        ensemble = StrategyEnsemble(
            strategies=[AlwaysLong()],
            method="unknown",
        )
        with pytest.raises(ValueError, match="Unknown ensemble method"):
            ensemble.generate_signal(df)

    def test_name_property(self):
        ensemble = StrategyEnsemble(
            strategies=[AlwaysLong(), AlwaysShort()],
        )
        assert "AlwaysLong" in ensemble.name
        assert "AlwaysShort" in ensemble.name

    def test_min_bars_is_max(self):
        class HighMinBars(Strategy):
            timeframe = "1h"
            min_bars = 200
            DEFAULT_PARAMS = {}

            @property
            def name(self) -> str:
                return "HighMinBars"

            def generate_signal(self, df: pd.DataFrame) -> pd.Series:
                return pd.Series(0, index=df.index, dtype=int)

        ensemble = StrategyEnsemble(
            strategies=[AlwaysLong(), HighMinBars()],
        )
        assert ensemble.min_bars == 200

    def test_default_weights(self):
        df = _make_df(10)
        ensemble = StrategyEnsemble(
            strategies=[AlwaysLong(), AlwaysShort()],
        )
        assert ensemble.weights == [1.0, 1.0]
        signal = ensemble.generate_signal(df)
        assert (signal == 0).all()
