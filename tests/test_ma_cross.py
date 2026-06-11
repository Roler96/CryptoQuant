"""Tests for MACrossover strategy."""

import pandas as pd
import pytest

from strategies.example.ma_cross import MACrossover


@pytest.fixture
def strategy():
    return MACrossover()


@pytest.fixture
def sample_data():
    """Data with clear trend change for crossover detection."""
    n = 200
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    # First 100 bars: flat around 100, next 100 bars: uptrend
    close = pd.Series(
        [100.0] * 50 + [101.0] * 50 + list(range(102, 202)),
        index=dates,
        dtype=float,
    )
    df = pd.DataFrame(
        {
            "open": close * 0.999,
            "high": close * 1.002,
            "low": close * 0.998,
            "close": close,
            "volume": 1000.0,
        },
        index=dates,
    )
    return df


class TestMACrossover:
    def test_generates_signal_with_correct_index(self, strategy, sample_data):
        signal = strategy.generate_signal(sample_data)
        assert isinstance(signal, pd.Series)
        assert len(signal) == len(sample_data)
        assert (signal.index == sample_data.index).all()

    def test_signal_values_are_valid(self, strategy, sample_data):
        signal = strategy.generate_signal(sample_data)
        assert signal.isin([-1, 0, 1]).all()

    def test_insufficient_bars_raises(self, strategy):
        df = pd.DataFrame(
            {"open": [1], "high": [1], "low": [1], "close": [1], "volume": [1]}
        )
        with pytest.raises(Exception, match="at least"):
            strategy.generate_signal(df)

    def test_long_only_no_short_signals(self):
        strategy = MACrossover({"fast": 5, "slow": 15, "signal_type": "long_only"})
        n = 150
        dates = pd.date_range("2024-01-01", periods=n, freq="1h")
        close = pd.Series(list(range(100, 100 - n, -1)), index=dates, dtype=float)
        df = pd.DataFrame(
            {
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 1000.0,
            },
            index=dates,
        )
        signal = strategy.generate_signal(df)
        assert (signal >= 0).all()  # No -1 signals

    def test_default_params(self, strategy):
        assert strategy.params["fast"] == 12
        assert strategy.params["slow"] == 26
        assert strategy.params["signal_type"] == "both"

    def test_custom_params(self):
        strategy = MACrossover({"fast": 5, "slow": 20})
        assert strategy.params["fast"] == 5
        assert strategy.params["slow"] == 20

    def test_name(self, strategy):
        assert strategy.name == "MACrossover"

    def test_timeframe(self, strategy):
        assert strategy.timeframe == "1h"

    def test_min_bars(self, strategy):
        assert strategy.min_bars == 100
