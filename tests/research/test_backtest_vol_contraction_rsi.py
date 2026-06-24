"""Tests for VolContractionRSI strategy."""

import pandas as pd
import pytest

from research.backtest_vol_contraction_rsi import VolContractionRSI


@pytest.fixture
def strategy():
    return VolContractionRSI()


@pytest.fixture
def sample_data():
    """Generate OHLCV data with enough bars for all indicators."""
    n = 350
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    # Create price series with some oscillation to trigger BB squeeze + RSI moves
    import numpy as np
    np.random.seed(42)
    base = 100.0
    # Sinusoidal to create volatility cycles (contraction/expansion)
    t = np.linspace(0, 8 * np.pi, n)
    close = base + 5 * np.sin(t) + np.random.randn(n) * 0.3

    df = pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.3,
            "low": close - 0.3,
            "close": close,
            "volume": 1000.0,
        },
        index=dates,
    )
    return df


class TestVolContractionRSI:
    def test_instantiation_with_defaults(self, strategy):
        """Strategy instantiates with correct default params."""
        assert strategy.name == "VolContractionRSI"
        assert strategy.timeframe == "1h"
        assert strategy.min_bars == 300
        assert strategy.version == "1.0.0"
        assert strategy.params["bb_period"] == 20
        assert strategy.params["bb_std"] == 2.0
        assert strategy.params["rsi_period"] == 14
        assert strategy.params["oversold_threshold"] == 30
        assert strategy.params["overbought_threshold"] == 70
        assert strategy.params["exit_threshold"] == 50
        assert strategy.params["squeeze_pct"] == 10
        assert strategy.params["squeeze_lookback"] == 100

    def test_instantiation_with_custom_params(self):
        """Strategy accepts parameter overrides."""
        s = VolContractionRSI({"bb_period": 15, "rsi_period": 10})
        assert s.params["bb_period"] == 15
        assert s.params["rsi_period"] == 10
        # Unspecified params use defaults
        assert s.params["bb_std"] == 2.0

    def test_signal_shape_and_index(self, strategy, sample_data):
        """Signal has same length and index as input DataFrame."""
        signal = strategy.generate_signal(sample_data)
        assert isinstance(signal, pd.Series)
        assert len(signal) == len(sample_data)
        assert (signal.index == sample_data.index).all()

    def test_signal_values_are_valid(self, strategy, sample_data):
        """Signal contains only valid values: -1, 0, 1."""
        signal = strategy.generate_signal(sample_data)
        assert signal.isin([-1, 0, 1]).all()

    def test_insufficient_bars_raises(self, strategy):
        """StrategyError raised when DataFrame has fewer than min_bars."""
        df = pd.DataFrame(
            {
                "open": [1],
                "high": [1],
                "low": [1],
                "close": [1],
                "volume": [1],
            }
        )
        with pytest.raises(Exception, match="at least"):
            strategy.generate_signal(df)

    def test_missing_columns_raises(self, strategy):
        """StrategyError raised when required columns are missing."""
        df = pd.DataFrame({"close": [100] * 400})
        with pytest.raises(Exception, match="missing required columns"):
            strategy.generate_signal(df)

    def test_returns_integer_dtype(self, strategy, sample_data):
        """Signal series has integer dtype."""
        signal = strategy.generate_signal(sample_data)
        assert signal.dtype == int

    def test_both_long_and_short_possible(self, strategy, sample_data):
        """The strategy can generate both 1 and -1 signals."""
        signal = strategy.generate_signal(sample_data)
        unique = set(signal.unique())
        assert 1 in unique, "Should have at least one long signal"
        assert -1 in unique, "Should have at least one short signal"
