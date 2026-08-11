"""Shared-engine execution and frozen URA performance statistics."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from cq.context import Series
from cq.core.types import CostModel, MarketSpec, Sizing
from cq.engine.loop import RunResult, run_backtest
from cq.research.ura.data import HOUR_MS
from cq.research.ura.signals import SignalEvent, UraConfig, UraStrategy

DAY_MS = 24 * HOUR_MS
INITIAL_CASH = 10_000.0


class IntegrityError(RuntimeError):
    """The accepted schedule cannot be executed under the frozen contract."""


@dataclass(frozen=True)
class EpisodeResult:
    entry_time: int
    exit_time: int
    pnl: float
    account_return: float


@dataclass(frozen=True)
class Performance:
    final_equity: float
    total_return: float
    cagr: float | None
    sharpe: float
    max_drawdown: float
    longest_drawdown_hours: int
    longest_drawdown_start: int | None
    longest_drawdown_end: int | None
    episodes: int
    fills: int
    win_rate: float
    profit_factor: float
    daily_observations: int
    open_position: bool
    best_1_concentration: float | None
    best_3_concentration: float | None
    best_5_concentration: float | None


@dataclass(frozen=True)
class UraOutcome:
    result: RunResult
    metrics: Performance
    episodes: tuple[EpisodeResult, ...]
    daily_returns: np.ndarray


def validate_execution_bars(series: Series, events: list[SignalEvent]) -> None:
    for event in events:
        if float(series.volume[event.entry_index]) <= 0.0:
            raise IntegrityError(
                f"zero-volume entry bar at {int(series.ts[event.entry_index])}"
            )
        if float(series.volume[event.exit_index]) <= 0.0:
            raise IntegrityError(
                f"zero-volume exit bar at {int(series.ts[event.exit_index])}"
            )


def run_ura(
    series: Series,
    config: UraConfig,
    costs: CostModel,
    *,
    expected_events: list[SignalEvent],
    evaluation_start_ms: int | None = None,
) -> UraOutcome:
    validate_execution_bars(series, expected_events)
    result = run_backtest(
        UraStrategy(config),
        series,
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
        sizing=Sizing.ON_ENTRY,
        dust_fraction=0.0,
        evaluation_start_ms=evaluation_start_ms,
    )
    if result.rejections:
        raise IntegrityError(f"engine rejected {len(result.rejections)} accepted orders")
    expected_fill_times = [
        timestamp
        for event in expected_events
        for timestamp in (int(series.ts[event.entry_index]), int(series.ts[event.exit_index]))
    ]
    actual_fill_times = [fill.ts for fill in result.fills]
    if actual_fill_times != expected_fill_times:
        raise IntegrityError(
            f"schedule/engine fill mismatch: expected {expected_fill_times[:6]}, "
            f"got {actual_fill_times[:6]}"
        )
    if not result.portfolio.is_flat:
        raise IntegrityError("engine ended with an open position")

    episodes = episode_results(result)
    daily_returns = daily_returns_from_result(result)
    metrics = performance_from_result(result, episodes, daily_returns)
    return UraOutcome(result, metrics, episodes, daily_returns)


def episode_results(result: RunResult) -> tuple[EpisodeResult, ...]:
    filled = [record for record in result.transactions if record.status == "filled"]
    if len(filled) % 2:
        raise IntegrityError("filled transaction count is not even")
    episodes: list[EpisodeResult] = []
    for index in range(0, len(filled), 2):
        entry, exit_ = filled[index : index + 2]
        if entry.side != "buy" or exit_.side != "sell":
            raise IntegrityError("filled transactions are not buy/sell episode pairs")
        pnl = exit_.cash_after - entry.cash_before
        episodes.append(
            EpisodeResult(
                entry.execution_time,
                exit_.execution_time,
                pnl,
                pnl / entry.cash_before,
            )
        )
    return tuple(episodes)


def daily_returns_from_result(result: RunResult) -> np.ndarray:
    daily_equity = [
        equity
        for ts, equity in zip(result.timestamps, result.equity, strict=True)
        if (ts // HOUR_MS) % 24 == 23
    ]
    returns: list[float] = []
    previous = result.initial_cash
    for equity in daily_equity:
        returns.append(equity / previous - 1.0)
        previous = equity
    return np.asarray(returns, dtype=float)


def performance_from_result(
    result: RunResult,
    episodes: tuple[EpisodeResult, ...],
    daily_returns: np.ndarray,
) -> Performance:
    equity = np.asarray([result.initial_cash, *result.equity], dtype=float)
    running_max = np.maximum.accumulate(equity)
    drawdowns = equity / running_max - 1.0
    max_drawdown = float(np.min(drawdowns))
    dd_hours, dd_start, dd_end = _longest_drawdown(
        result.timestamps, equity, running_max
    )
    if len(daily_returns) >= 2:
        deviation = float(np.std(daily_returns, ddof=1))
        sharpe = (
            float(np.mean(daily_returns)) / deviation * math.sqrt(365.0)
            if deviation > 0
            else 0.0
        )
    else:
        sharpe = 0.0

    calendar_days = (
        (result.timestamps[-1] + HOUR_MS - result.timestamps[0]) / DAY_MS
        if result.timestamps
        else 0.0
    )
    cagr = (
        (result.final_equity / result.initial_cash) ** (365.0 / calendar_days) - 1.0
        if result.final_equity > 0 and calendar_days > 0
        else None
    )
    pnls = np.asarray([episode.pnl for episode in episodes], dtype=float)
    wins = int(np.count_nonzero(pnls > 0.0))
    positive = float(np.sum(pnls[pnls > 0.0]))
    negative = float(np.sum(pnls[pnls < 0.0]))
    if positive <= 0:
        profit_factor = 0.0
    elif negative == 0:
        profit_factor = math.inf
    else:
        profit_factor = positive / abs(negative)

    concentrations = tuple(_concentration(pnls, count) for count in (1, 3, 5))
    return Performance(
        final_equity=result.final_equity,
        total_return=result.total_return,
        cagr=cagr,
        sharpe=sharpe,
        max_drawdown=max_drawdown,
        longest_drawdown_hours=dd_hours,
        longest_drawdown_start=dd_start,
        longest_drawdown_end=dd_end,
        episodes=len(episodes),
        fills=len(result.fills),
        win_rate=wins / len(episodes) if episodes else 0.0,
        profit_factor=profit_factor,
        daily_observations=len(daily_returns),
        open_position=not result.portfolio.is_flat,
        best_1_concentration=concentrations[0],
        best_3_concentration=concentrations[1],
        best_5_concentration=concentrations[2],
    )


def _concentration(pnls: np.ndarray, count: int) -> float | None:
    positives = pnls[pnls > 0.0]
    denominator = float(np.sum(positives))
    if denominator <= 0:
        return None
    ordered = np.sort(positives)[::-1]
    return float(np.sum(ordered[:count])) / denominator


def _longest_drawdown(
    timestamps: list[int], equity: np.ndarray, running_max: np.ndarray
) -> tuple[int, int | None, int | None]:
    if len(equity) <= 1:
        return 0, None, None
    best_hours = 0
    best_start: int | None = None
    best_end: int | None = None
    active_peak_index: int | None = None
    for index in range(1, len(equity)):
        if equity[index] < running_max[index]:
            if active_peak_index is None:
                active_peak_index = index - 1
            continue
        if active_peak_index is not None:
            hours = index - active_peak_index
            if hours > best_hours:
                best_hours = hours
                best_start = _equity_timestamp(timestamps, active_peak_index)
                best_end = _equity_timestamp(timestamps, index)
            active_peak_index = None
    if active_peak_index is not None:
        index = len(equity) - 1
        hours = index - active_peak_index
        if hours > best_hours:
            best_hours = hours
            best_start = _equity_timestamp(timestamps, active_peak_index)
            best_end = _equity_timestamp(timestamps, index)
    return best_hours, best_start, best_end


def _equity_timestamp(timestamps: list[int], equity_index: int) -> int | None:
    if not timestamps:
        return None
    if equity_index == 0:
        return timestamps[0]
    return timestamps[equity_index - 1] + HOUR_MS
