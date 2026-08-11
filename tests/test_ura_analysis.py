"""URA v1 execution and metric tests."""

from __future__ import annotations

import numpy as np
import pytest

from cq.context import Series
from cq.core.types import CostModel
from cq.research.ura.analysis import (
    IntegrityError,
    run_ura,
    validate_execution_bars,
)
from cq.research.ura.signals import UraConfig, build_schedule

HOUR = 3_600_000


def _series(length: int = 120) -> Series:
    reference = [1.0] * 6 + [2.0] * 6 + [4.0] * 12 + [3.5]
    closes = np.asarray((reference * ((length // len(reference)) + 1))[:length])
    return Series(
        "DOGE-USDT",
        "1h",
        np.arange(length, dtype=np.int64) * HOUR,
        closes,
        closes,
        closes,
        closes,
        np.full(length, 100.0),
    )


def test_execution_integrity_rejects_zero_volume_at_accepted_entry() -> None:
    series = _series()
    events = build_schedule(series, UraConfig(evaluation_end_ms=len(series) * HOUR))
    volume = np.array(series.volume)
    volume[events[0].entry_index] = 0.0
    damaged = Series(
        series.inst_id,
        series.timeframe,
        series.ts,
        series.open,
        series.high,
        series.low,
        series.close,
        volume,
    )

    with pytest.raises(IntegrityError, match="entry"):
        validate_execution_bars(damaged, events)


def test_engine_run_reports_closed_episodes_daily_sharpe_and_drawdown() -> None:
    series = _series()
    config = UraConfig(evaluation_end_ms=len(series) * HOUR)
    events = build_schedule(series, config)

    outcome = run_ura(
        series,
        config,
        CostModel(fee_bps=10.0, slippage_bps=5.0),
        expected_events=events,
    )

    assert outcome.metrics.episodes == len(events)
    assert outcome.metrics.fills == 2 * len(events)
    assert outcome.metrics.open_position is False
    assert outcome.metrics.daily_observations == 5
    assert outcome.metrics.max_drawdown <= 0.0
    assert np.isfinite(outcome.metrics.sharpe)
    assert len(outcome.episodes) == len(events)
