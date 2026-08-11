"""SPDP v2 causal signal, funnel, and frozen schedule tests."""

from __future__ import annotations

from itertools import pairwise

import numpy as np

from cq.context import Series
from cq.research.spdp.data import HOUR_MS, StudyData, make_quote_series
from cq.research.spdp.signals import (
    SpdpConfig,
    build_schedule,
    condition_funnel,
    signal_values,
)


def _panel(length: int = 820, signal_index: int = 742) -> StudyData:
    ts = np.arange(length, dtype=np.int64) * HOUR_MS
    returns = np.where(np.arange(length) % 2 == 0, 0.001, -0.001)
    close = np.exp(np.cumsum(returns))
    anchor = close[signal_index - 12]
    close[signal_index - 11 : signal_index + 1] = anchor * np.exp(
        np.linspace(0.01, 0.12, 12)
    )
    ones = np.ones(length, dtype=float)
    spot = Series("DOGE-USDT", "1h", ts, close, close, close, close, ones * 100)
    swap = Series("DOGE-USDT-SWAP", "1h", ts, close, close, close, close, ones * 100)
    spot_qv = ones * 10
    swap_qv = ones * 90
    spot_qv[signal_index - 11 : signal_index + 1] = 90
    swap_qv[signal_index - 11 : signal_index + 1] = 10
    return StudyData(
        spot=spot,
        swap=swap,
        spot_qv=make_quote_series("DOGE-USDT-QV", ts, spot_qv, spot.volume),
        swap_qv=make_quote_series("DOGE-USDT-SWAP-QV", ts, swap_qv, swap.volume),
        spot_raw_fingerprint="spot",
        swap_raw_fingerprint="swap",
    )


def test_signal_uses_only_closed_743_bar_window_and_has_frozen_values() -> None:
    data = _panel()
    t = 742
    feature = signal_values(
        data.spot.close[t - 742 : t + 1],
        data.spot_qv.close[t - 742 : t + 1],
        data.swap_qv.close[t - 742 : t + 1],
        data.spot_qv.volume[t - 742 : t + 1],
        data.swap_qv.volume[t - 742 : t + 1],
        SpdpConfig(),
    )

    assert feature is not None
    assert feature.current_share == 0.9
    assert feature.prior_share == 0.1
    assert feature.share_migration == 0.8
    assert feature.return_12h > 0.11

    changed = _panel()
    changed.spot.close.setflags(write=True)
    changed.spot.close[t + 1 :] = 10_000.0
    changed.spot.close.setflags(write=False)
    unchanged = signal_values(
        changed.spot.close[t - 742 : t + 1],
        changed.spot_qv.close[t - 742 : t + 1],
        changed.swap_qv.close[t - 742 : t + 1],
        changed.spot_qv.volume[t - 742 : t + 1],
        changed.swap_qv.volume[t - 742 : t + 1],
        SpdpConfig(),
    )
    assert unchanged == feature


def test_schedule_enters_next_open_exits_48h_later_and_blocks_overlap() -> None:
    data = _panel()
    events = build_schedule(data, SpdpConfig(evaluation_end_ms=len(data.spot) * HOUR_MS))

    first = events[0]
    assert first.decision_index == 742
    assert first.entry_index == 743
    assert first.exit_index == 791
    assert all(
        right.entry_index > left.exit_index
        for left, right in pairwise(events)
    )


def test_calendar_boundary_rejects_presegment_decision_and_funnel_is_monotone() -> None:
    data = _panel(signal_index=742)
    config = SpdpConfig(
        evaluation_start_ms=743 * HOUR_MS,
        evaluation_end_ms=len(data.spot) * HOUR_MS,
    )
    assert all(event.decision_index >= 743 for event in build_schedule(data, config))

    funnel = condition_funnel(data, SpdpConfig(evaluation_end_ms=len(data.spot) * HOUR_MS))
    ordered = [
        funnel["eligible_decisions"],
        funnel["positive_signal_window"],
        funnel["positive_sigma"],
        funnel["share_level"],
        funnel["share_migration"],
        funnel["positive_impulse"],
    ]
    assert ordered == sorted(ordered, reverse=True)
    assert funnel["accepted_schedule"] <= funnel["positive_impulse"]
