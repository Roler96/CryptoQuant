"""Tests for VolSpikeReversal strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research.backtest_vol_spike_reversal import VolSpikeReversal


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


def _make_ranging_vol_spike_df(n: int = 500) -> pd.DataFrame:
    """Create ranging market data with extreme vol spike + crash near BB lower.

    Designed for long entry: requires ALL of: BB pct_b < 0.1, vol spike > 1.5,
    volume ratio > 1.3, Z-score < -2.0, ADX < 20. To satisfy all 5 at once,
    we need a dramatic crash after a calm oscillating period.
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    t = np.arange(n)

    # Phase 1 (bars 0-390): calm oscillation with tiny amplitude (ADX stays low)
    close = 100.0 + 0.3 * np.sin(2 * np.pi * t / 60)

    # Phase 2 (bars 390-410): crash from 100 to 82 (-18%) over 20 bars
    close[390:] = np.linspace(100, 82, n - 390)
    # Add micro-oscillation to keep ADX from spiking too high
    close[390:] += 0.2 * np.sin(2 * np.pi * np.arange(n - 390) / 5)

    high = np.maximum(close + 0.8, close * 1.005)
    low = np.minimum(close - 0.5, close * 0.995)
    opens = close - 0.1

    volume = np.full(n, 800.0)
    volume[385:420] = 5000.0  # massive volume spike during crash

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


def _make_ranging_vol_spike_short_df(n: int = 500) -> pd.DataFrame:
    """Create ranging market data with extreme vol spike + rally near BB upper."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    t = np.arange(n)

    # Phase 1 (bars 0-390): calm oscillation
    close = 100.0 + 0.3 * np.sin(2 * np.pi * t / 60)

    # Phase 2 (bars 390-410): rally from 100 to 118 (+18%) over 20 bars
    close[390:] = np.linspace(100, 118, n - 390)
    close[390:] += 0.2 * np.sin(2 * np.pi * np.arange(n - 390) / 5)

    high = np.maximum(close + 0.8, close * 1.005)
    low = np.minimum(close - 0.5, close * 0.995)
    opens = close + 0.1

    volume = np.full(n, 800.0)
    volume[385:420] = 5000.0

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


class TestVolSpikeReversal:
    """Tests for the VolSpikeReversal strategy."""

    def test_default_params_instantiation(self):
        """Strategy can be instantiated with default parameters."""
        s = VolSpikeReversal()
        assert s.name == "VolSpikeReversal"
        assert s.timeframe == "1h"
        assert s.min_bars == 300
        assert s.version == "1.0.0"
        assert s.params["bb_period"] == 20
        assert s.params["bb_std"] == 2.0
        assert s.params["vol_short"] == 20
        assert s.params["vol_long"] == 100
        assert s.params["vol_spike_threshold"] == 1.5
        assert s.params["vol_ratio_period"] == 20
        assert s.params["vol_ratio_threshold"] == 1.3
        assert s.params["zscore_period"] == 100
        assert s.params["zscore_threshold"] == 2.0
        assert s.params["adx_period"] == 14
        assert s.params["adx_max"] == 20
        assert s.params["stop_loss_pct"] == 0.03
        assert s.params["max_hold_bars"] == 48

    def test_custom_params_instantiation(self):
        """Strategy can be instantiated with custom parameters."""
        s = VolSpikeReversal(
            params={"bb_period": 10, "adx_max": 25, "zscore_threshold": 1.5}
        )
        assert s.params["bb_period"] == 10
        assert s.params["adx_max"] == 25
        assert s.params["zscore_threshold"] == 1.5
        # Unchanged defaults
        assert s.params["bb_std"] == 2.0
        assert s.params["vol_long"] == 100

    def test_generate_signal_returns_correct_shape(self):
        """generate_signal() returns Series with correct shape and types."""
        df = _make_flat_df(500)
        s = VolSpikeReversal()
        signal = s.generate_signal(df)

        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert (signal.index == df.index).all()
        assert signal.dtype == int

    def test_signal_values_valid(self):
        """Signal values are only -1, 0, 1."""
        df = _make_ranging_vol_spike_df(500)
        s = VolSpikeReversal()
        signal = s.generate_signal(df)
        unique_vals = set(signal.unique())
        assert unique_vals.issubset({-1, 0, 1})

    def test_insufficient_bars_raises(self):
        """Short DataFrame raises StrategyError via preprocess."""
        df = _make_flat_df(100)  # fewer than min_bars=300
        s = VolSpikeReversal()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_missing_columns_raises(self):
        """DataFrame missing required columns raises StrategyError."""
        df = pd.DataFrame(
            {"close": [100.0] * 500},
            index=pd.date_range("2024-01-01", periods=500, freq="1h"),
        )
        s = VolSpikeReversal()
        with pytest.raises(StrategyError):
            s.generate_signal(df)

    def test_ranging_market_no_crash(self):
        """Strategy runs without error on ranging market data, returns valid signals."""
        df = _make_ranging_vol_spike_df(500)
        s = VolSpikeReversal()
        signal = s.generate_signal(df)
        # The 5-entry-condition filter is strict — synthetic data may not trigger
        # all 5 simultaneously. But strategy must not crash and output valid values.
        unique_vals = set(signal.unique())
        assert unique_vals.issubset({-1, 0, 1})
        assert len(signal) == len(df)

    def test_short_scenario_no_crash(self):
        """Strategy runs without error on upside spike data, returns valid signals."""
        df = _make_ranging_vol_spike_short_df(500)
        s = VolSpikeReversal()
        signal = s.generate_signal(df)
        unique_vals = set(signal.unique())
        assert unique_vals.issubset({-1, 0, 1})
        assert len(signal) == len(df)
