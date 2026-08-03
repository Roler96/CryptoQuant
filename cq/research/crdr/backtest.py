"""Fixed-contract, non-overlapping CRDR episode simulator."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import cast

import numpy as np
import pandas as pd

from cq.research.crdr.data import StudyPanel
from cq.research.crdr.signals import SignalEvent


@dataclass(frozen=True)
class Episode:
    checkpoint: pd.Timestamp
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    weights: tuple[tuple[str, float], ...]
    gross_return: float
    net_return: float
    long_net_return: float
    short_net_return: float


@dataclass(frozen=True)
class BacktestResult:
    hourly_returns: pd.Series
    equity: pd.Series
    episodes: tuple[Episode, ...]


@dataclass
class _ActiveEpisode:
    event: SignalEvent
    start_equity: float
    entry_prices: dict[str, float]


def run_backtest(
    panel: StudyPanel,
    events: list[SignalEvent],
    *,
    cost_bps: float,
    funding_penalty_bps: float = 0.0,
) -> BacktestResult:
    """Mark fixed entry contracts open-to-open and deduct explicit turnover costs."""
    if not np.isfinite(cost_bps) or cost_bps < 0:
        raise ValueError("cost_bps must be finite and non-negative")
    if not np.isfinite(funding_penalty_bps) or funding_penalty_bps < 0:
        raise ValueError("funding_penalty_bps must be finite and non-negative")
    ordered_events = sorted(events, key=lambda event: event.entry_time)
    for previous, current in pairwise(ordered_events):
        if current.entry_time < previous.exit_time:
            raise ValueError("CRDR events overlap")

    index = panel.opens.index
    if index.empty:
        raise ValueError("CRDR backtest requires a non-empty hourly panel")
    entry_events = {event.entry_time: event for event in ordered_events}
    if len(entry_events) != len(ordered_events):
        raise ValueError("CRDR events overlap at the same entry time")
    for event in ordered_events:
        _validate_event(panel, event)

    cost_rate = cost_bps / 10_000.0
    funding_rate = funding_penalty_bps / 10_000.0
    equity_values = np.ones(len(index), dtype=float)
    active: _ActiveEpisode | None = None
    episodes: list[Episode] = []

    for position, timestamp_value in enumerate(index):
        timestamp = cast(pd.Timestamp, timestamp_value)
        current_equity = 1.0 if position == 0 else equity_values[position - 1]
        previous_timestamp = cast(pd.Timestamp, index[position - 1]) if position else None

        if active is not None and previous_timestamp is not None:
            if timestamp <= active.event.exit_time:
                hourly_pnl = _interval_pnl(
                    panel,
                    active,
                    previous_timestamp,
                    timestamp,
                )
                current_equity += active.start_equity * hourly_pnl

            if timestamp == active.event.exit_time:
                episode = _finish_episode(
                    panel,
                    active,
                    cost_rate=cost_rate,
                    funding_rate=funding_rate,
                )
                exit_charge = active.start_equity * (
                    cost_rate * _gross_exposure(active.event) + funding_rate
                )
                current_equity -= exit_charge
                episodes.append(episode)
                active = None

        event = entry_events.get(timestamp)
        if event is not None:
            if active is not None:
                raise ValueError("CRDR events overlap")
            start_equity = current_equity
            weights = dict(event.weights)
            selected = [instrument for instrument, weight in weights.items() if weight]
            entry_prices = {
                instrument: float(panel.opens.loc[timestamp, instrument])
                for instrument in selected
            }
            active = _ActiveEpisode(event, start_equity, entry_prices)
            current_equity -= start_equity * cost_rate * _gross_exposure(event)

        if not np.isfinite(current_equity) or current_equity <= 0:
            raise RuntimeError(f"CRDR equity became non-positive at {timestamp}")
        equity_values[position] = current_equity

    if active is not None:
        raise ValueError("CRDR event exits after the available panel")

    equity = pd.Series(equity_values, index=index, name="equity")
    hourly_returns = equity.pct_change(fill_method=None).fillna(0.0).rename("return")
    return BacktestResult(hourly_returns, equity, tuple(episodes))


def _validate_event(panel: StudyPanel, event: SignalEvent) -> None:
    if event.entry_time >= event.exit_time:
        raise ValueError("CRDR event exit must follow entry")
    if event.entry_time not in panel.opens.index or event.exit_time not in panel.opens.index:
        raise ValueError("CRDR event execution time is outside the panel")
    weights = dict(event.weights)
    if not np.isclose(sum(weights.values()), 0.0, atol=1e-12):
        raise ValueError("CRDR event weights must be dollar neutral")
    if not np.isclose(sum(abs(weight) for weight in weights.values()), 1.0, atol=1e-12):
        raise ValueError("CRDR event gross exposure must equal one")
    selected = [instrument for instrument, weight in weights.items() if weight]
    execution_index = panel.opens.loc[event.entry_time : event.exit_time].index
    selected_opens = panel.opens.loc[execution_index, selected].to_numpy(dtype=float)
    if not np.isfinite(selected_opens).all() or (selected_opens <= 0).any():
        raise ValueError("CRDR invalid execution open")


def _gross_exposure(event: SignalEvent) -> float:
    return float(sum(abs(weight) for _, weight in event.weights))


def _interval_pnl(
    panel: StudyPanel,
    active: _ActiveEpisode,
    previous: pd.Timestamp,
    current: pd.Timestamp,
) -> float:
    pnl = 0.0
    for instrument, weight in active.event.weights:
        if not weight:
            continue
        price_change = float(
            panel.opens.loc[current, instrument] - panel.opens.loc[previous, instrument]
        )
        pnl += weight * price_change / active.entry_prices[instrument]
    return pnl


def _finish_episode(
    panel: StudyPanel,
    active: _ActiveEpisode,
    *,
    cost_rate: float,
    funding_rate: float,
) -> Episode:
    gross_return = 0.0
    long_gross = 0.0
    short_gross = 0.0
    long_exposure = 0.0
    short_exposure = 0.0
    for instrument, weight in active.event.weights:
        if not weight:
            continue
        asset_return = (
            float(panel.opens.loc[active.event.exit_time, instrument])
            / active.entry_prices[instrument]
            - 1.0
        )
        contribution = weight * asset_return
        gross_return += contribution
        if weight > 0:
            long_gross += contribution
            long_exposure += weight
        else:
            short_gross += contribution
            short_exposure += abs(weight)

    gross_exposure = long_exposure + short_exposure
    total_cost = 2.0 * cost_rate * gross_exposure + funding_rate
    long_cost = 2.0 * cost_rate * long_exposure + funding_rate * long_exposure / gross_exposure
    short_cost = 2.0 * cost_rate * short_exposure + funding_rate * short_exposure / gross_exposure
    return Episode(
        checkpoint=active.event.checkpoint,
        entry_time=active.event.entry_time,
        exit_time=active.event.exit_time,
        weights=active.event.weights,
        gross_return=float(gross_return),
        net_return=float(gross_return - total_cost),
        long_net_return=float(long_gross - long_cost),
        short_net_return=float(short_gross - short_cost),
    )
