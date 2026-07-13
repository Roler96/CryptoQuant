"""Tests for the frozen DOGE Donchian strategy semantics."""

import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from strategies.doge_donchian_trend import DogeDonchianTrend


def _bars(n: int = 181, last_close: float | None = None) -> pd.DataFrame:
    close = np.full(n, 100.0)
    if last_close is not None:
        close[-1] = last_close
    return pd.DataFrame(
        {
            "open": close,
            "high": np.where(np.arange(n) == n - 1, close, 101.0),
            "low": np.where(np.arange(n) == n - 1, close, 99.0),
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=pd.date_range("2025-01-01", periods=n, freq="4h", tz="UTC"),
    )


def test_flat_long_breakout_uses_prior_channel():
    signal = DogeDonchianTrend().generate_signal(_bars(last_close=102.0))
    assert signal.iloc[-1] == 1


def test_flat_short_breakout_uses_prior_channel():
    signal = DogeDonchianTrend().generate_signal(_bars(last_close=98.0))
    assert signal.iloc[-1] == -1


def test_long_uses_exit_channel_not_entry_channel():
    strategy = DogeDonchianTrend()
    df = _bars(last_close=98.0)
    signal = strategy.generate_signal_for_position(df, "long")
    assert signal.iloc[-1] == -1


def test_short_uses_exit_channel_not_entry_channel():
    strategy = DogeDonchianTrend()
    df = _bars(last_close=102.0)
    signal = strategy.generate_signal_for_position(df, "short")
    assert signal.iloc[-1] == 1


def test_current_bar_high_does_not_move_its_own_entry_threshold():
    df = _bars(last_close=102.0)
    df.iloc[-1, df.columns.get_loc("high")] = 200.0
    assert DogeDonchianTrend().generate_signal(df).iloc[-1] == 1


def test_invalid_parameters_fail():
    with pytest.raises(StrategyError):
        DogeDonchianTrend({"entry_bars": 60, "exit_bars": 60})
