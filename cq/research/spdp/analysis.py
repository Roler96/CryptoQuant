"""Shared-engine execution and frozen SPDP v2 metrics."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from cq.context import series_fingerprint
from cq.core.types import CostModel, MarketSpec, Sizing
from cq.engine.loop import RunResult, run_backtest
from cq.research.spdp.data import StudyData
from cq.research.spdp.signals import SignalEvent, SpdpConfig, SpdpStrategy
from cq.research.ura.analysis import (
    EpisodeResult,
    Performance,
    daily_returns_from_result,
    episode_results,
    performance_from_result,
)

INITIAL_CASH = 10_000.0


class IntegrityError(RuntimeError):
    """The accepted SPDP schedule cannot satisfy the frozen contract."""


@dataclass(frozen=True)
class SpdpOutcome:
    result: RunResult
    metrics: Performance
    episodes: tuple[EpisodeResult, ...]
    daily_returns: np.ndarray


def validate_execution_bars(data: StudyData, events: list[SignalEvent]) -> None:
    for event in events:
        for label, series in (
            ("spot", data.spot_qv),
            ("swap", data.swap_qv),
        ):
            for side, index in (
                ("entry", event.entry_index),
                ("exit", event.exit_index),
            ):
                if float(series.volume[index]) <= 0.0 or float(series.close[index]) <= 0.0:
                    raise IntegrityError(
                        f"degenerate {label} {side} bar at {int(series.ts[index])}"
                    )


def run_spdp(
    data: StudyData,
    config: SpdpConfig,
    costs: CostModel,
    *,
    expected_events: list[SignalEvent],
) -> SpdpOutcome:
    validate_execution_bars(data, expected_events)
    auxiliaries = [data.spot_qv, data.swap_qv]
    result = run_backtest(
        SpdpStrategy(config),
        data.spot,
        MarketSpec(
            "DOGE-USDT",
            "spot",
            lot_size=0.0,
            min_notional=0.0,
            max_leverage=1.0,
            maintenance_margin_rate=0.0,
            contract_size=1.0,
        ),
        initial_cash=INITIAL_CASH,
        costs=costs,
        aux=auxiliaries,
        sizing=Sizing.ON_ENTRY,
        dust_fraction=0.0,
        evaluation_start_ms=config.evaluation_start_ms,
    )
    if result.rejections:
        raise IntegrityError(f"engine rejected {len(result.rejections)} accepted orders")

    expected_aux = tuple(
        (*series.key, series_fingerprint(series)) for series in auxiliaries
    )
    if result.manifest.aux_fingerprints != expected_aux:
        raise IntegrityError("engine manifest does not bind the frozen auxiliary order")
    if result.aux_keys != tuple(series.key for series in auxiliaries):
        raise IntegrityError("engine auxiliary keys disagree with the frozen order")

    expected_fill_times = [
        timestamp
        for event in expected_events
        for timestamp in (
            int(data.spot.ts[event.entry_index]),
            int(data.spot.ts[event.exit_index]),
        )
    ]
    actual_fill_times = [fill.ts for fill in result.fills]
    if actual_fill_times != expected_fill_times:
        raise IntegrityError(
            f"schedule/engine fill mismatch: expected {expected_fill_times[:6]}, "
            f"got {actual_fill_times[:6]}"
        )
    if len(result.fills) != 2 * len(expected_events):
        raise IntegrityError("fill count is not exactly twice the episode count")
    if not result.portfolio.is_flat:
        raise IntegrityError("engine ended with an open position")

    episodes = episode_results(result)
    daily_returns = daily_returns_from_result(result)
    metrics = performance_from_result(result, episodes, daily_returns)
    return SpdpOutcome(result, metrics, episodes, daily_returns)
