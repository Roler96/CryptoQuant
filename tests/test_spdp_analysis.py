"""SPDP v2 shared-engine execution and provenance tests."""

from __future__ import annotations

import numpy as np

from cq.context import Series, series_fingerprint
from cq.core.types import CostModel
from cq.research.spdp.analysis import run_spdp, validate_execution_bars
from cq.research.spdp.data import HOUR_MS, StudyData, make_quote_series
from cq.research.spdp.signals import SpdpConfig, build_schedule


def _panel(length: int = 820, signal_index: int = 742) -> StudyData:
    ts = np.arange(length, dtype=np.int64) * HOUR_MS
    returns = np.where(np.arange(length) % 2 == 0, 0.001, -0.001)
    close = np.exp(np.cumsum(returns))
    anchor = close[signal_index - 12]
    close[signal_index - 11 : signal_index + 1] = anchor * np.exp(
        np.linspace(0.01, 0.12, 12)
    )
    volume = np.full(length, 100.0)
    spot = Series("DOGE-USDT", "1h", ts, close, close, close, close, volume)
    swap = Series("DOGE-USDT-SWAP", "1h", ts, close, close, close, close, volume)
    spot_quote = np.full(length, 10.0)
    swap_quote = np.full(length, 90.0)
    spot_quote[signal_index - 11 : signal_index + 1] = 90.0
    swap_quote[signal_index - 11 : signal_index + 1] = 10.0
    return StudyData(
        spot=spot,
        swap=swap,
        spot_qv=make_quote_series("DOGE-USDT-QV", ts, spot_quote, volume),
        swap_qv=make_quote_series("DOGE-USDT-SWAP-QV", ts, swap_quote, volume),
        spot_raw_fingerprint="spot",
        swap_raw_fingerprint="swap",
    )


def test_engine_fills_frozen_schedule_and_binds_both_aux_series() -> None:
    data = _panel()
    config = SpdpConfig(evaluation_end_ms=len(data.spot) * 3_600_000)
    events = build_schedule(data, config)
    validate_execution_bars(data, events)

    outcome = run_spdp(
        data,
        config,
        CostModel(fee_bps=10.0, slippage_bps=5.0),
        expected_events=events,
    )

    assert [fill.ts for fill in outcome.result.fills] == [
        timestamp
        for event in events
        for timestamp in (int(data.spot.ts[event.entry_index]), int(data.spot.ts[event.exit_index]))
    ]
    assert outcome.metrics.episodes == len(events)
    assert outcome.metrics.fills == 2 * len(events)
    assert outcome.metrics.open_position is False
    assert outcome.result.manifest.aux_fingerprints == (
        ("DOGE-USDT-QV", "1h", series_fingerprint(data.spot_qv)),
        ("DOGE-USDT-SWAP-QV", "1h", series_fingerprint(data.swap_qv)),
    )
