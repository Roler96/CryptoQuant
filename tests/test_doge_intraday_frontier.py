"""Tests for the second DOGE-only open intraday frontier scan."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.research_doge_intraday_frontier import (
    build_candidate_signals,
    evaluate_signal,
)


def _bars(count: int = 2_500) -> pd.DataFrame:
    rng = np.random.default_rng(20260811)
    returns = rng.normal(0.0, 0.002, count)
    close = 100.0 * np.exp(np.cumsum(returns))
    open_ = np.r_[100.0, close[:-1]]
    spread = rng.uniform(0.0005, 0.004, count)
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) * (1.0 + spread),
            "low": np.minimum(open_, close) * (1.0 - spread),
            "close": close,
            "volume": rng.lognormal(10.0, 0.5, count),
            "quote_volume": rng.lognormal(15.0, 0.5, count),
        },
        index=pd.date_range("2021-01-01", periods=count, freq="5min", tz="UTC"),
    )


def test_candidate_features_are_prefix_invariant() -> None:
    bars = _bars()
    prefix = bars.iloc[:2_200]

    full = {candidate.key: candidate.signal for candidate in build_candidate_signals(bars)}
    short = {candidate.key: candidate.signal for candidate in build_candidate_signals(prefix)}

    assert set(full) == set(short)
    for key in full:
        np.testing.assert_array_equal(full[key].iloc[: len(prefix)], short[key])


def test_frontier_contains_five_distinct_mechanism_families() -> None:
    families = {candidate.family for candidate in build_candidate_signals(_bars())}

    assert families == {
        "compression_release",
        "jump_aftershock",
        "liquidity_vacuum",
        "quarter_hour_impulse",
        "tail_recovery",
    }


def test_evaluator_enters_and_exits_at_future_opens() -> None:
    bars = _bars(12)
    bars.loc[:, "open"] = [90, 91, 92, 100, 101, 110, 111, 112, 113, 114, 115, 116]
    signal = pd.Series(0.0, index=bars.index)
    signal.iloc[2] = 1.0

    trial = evaluate_signal(
        bars,
        family="synthetic",
        variant="next-open",
        signal=signal,
        hold_bars=2,
        orientation=1.0,
        round_trip_cost=0.003,
    )

    assert trial.events == 1
    assert trial.mean_net_bps == pytest.approx(970.0)
    assert trial.total_return == pytest.approx(0.097)


def test_evaluator_blocks_overlapping_entries() -> None:
    bars = _bars(20)
    signal = pd.Series(1.0, index=bars.index)

    trial = evaluate_signal(
        bars,
        family="synthetic",
        variant="blocking",
        signal=signal,
        hold_bars=3,
        orientation=1.0,
        round_trip_cost=0.0,
    )

    assert trial.events == 4
