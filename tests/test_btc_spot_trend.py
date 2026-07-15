"""Causality and spot-contract tests for BtcSpotTrend."""

import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from research_btc_spot import BtcSpotTrend


def _bars(n: int = 1300) -> pd.DataFrame:
    close = np.full(n, 100.0)
    return pd.DataFrame(
        {
            "open": close,
            "high": np.full(n, 101.0),
            "low": np.full(n, 99.0),
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC"),
    )


def test_signal_contract_is_long_or_flat():
    signal = BtcSpotTrend().generate_signal(_bars())
    assert BtcSpotTrend.signal_is_position
    assert set(signal.unique()) <= {0, 1}


def test_breakout_uses_only_prior_channel():
    df = _bars()
    df.iloc[-1, df.columns.get_loc("close")] = 102.0
    df.iloc[-1, df.columns.get_loc("high")] = 1000.0

    assert BtcSpotTrend().generate_signal(df).iloc[-1] == 1


def test_future_mutation_cannot_change_past_signals():
    df = _bars()
    baseline = BtcSpotTrend().generate_signal(df)
    changed = df.copy()
    changed.iloc[-1, changed.columns.get_loc("close")] = 1000.0

    mutated = BtcSpotTrend().generate_signal(changed)

    pd.testing.assert_series_equal(baseline.iloc[:-1], mutated.iloc[:-1])


def test_existing_long_exits_below_prior_exit_channel():
    df = _bars()
    df.iloc[-1, df.columns.get_loc("close")] = 98.0

    signal = BtcSpotTrend().generate_signal_for_position(df, "long")

    assert signal.iloc[-1] == 0


def test_existing_long_is_not_lost_when_replay_starts_flat():
    df = _bars()

    signal = BtcSpotTrend().generate_signal_for_position(df, "long")

    assert signal.iloc[-1] == 1


@pytest.mark.parametrize(
    "params",
    [
        {"entry_bars": 60, "exit_bars": 60, "trend_bars": 600},
        {"entry_bars": 120, "exit_bars": 60, "trend_bars": 100},
        {"entry_bars": 1, "exit_bars": 0, "trend_bars": 1},
    ],
)
def test_invalid_parameters_fail(params):
    with pytest.raises(StrategyError):
        BtcSpotTrend(params)


def test_short_position_context_is_rejected():
    with pytest.raises(StrategyError, match="Unsupported spot"):
        BtcSpotTrend().generate_signal_for_position(_bars(), "short")
