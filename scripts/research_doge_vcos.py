"""Frozen open-development scan for DOGE volume-clock continuation (VCOS)."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

from cq.context import Series, series_fingerprint
from scripts.research_doge_intraday_frontier import load_bars

BARS_PER_DAY = 288
ROUND_TRIP_COST = 0.003
TARGET_WEIGHT = 0.25
MAX_SPAN = 72
JUMP_SHARE_MAX = 0.75


@dataclass(frozen=True)
class SeasonalState:
    profiles: np.ndarray
    day_ids: np.ndarray
    slots: np.ndarray
    base_dvol: np.ndarray


@dataclass(frozen=True)
class BucketFeatures:
    direction: np.ndarray
    coherence: np.ndarray
    jump_share: np.ndarray
    newest_span: np.ndarray
    older_span: np.ndarray
    valid: np.ndarray


@dataclass(frozen=True)
class VcosTrial:
    stage: str
    seasonal_days: int
    bucket_size: float
    coherence_threshold: float
    capacity_ratio: float
    hold_bars: int
    raw_signals: int
    episodes: int
    long_episodes: int
    short_episodes: int
    mean_net_bps_on_notional: float
    total_return: float
    sharpe: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    positive_years: int
    active_years: int
    year_returns: dict[str, float]
    long_pnl: float
    short_pnl: float
    best_five_positive_pnl_share: float
    largest_positive_slot_share: float


def build_seasonal_state(frame: pd.DataFrame, seasonal_days: int) -> SeasonalState:
    """Freeze each UTC day's seasonal curve from prior complete UTC days."""
    if seasonal_days <= 0:
        raise ValueError("seasonal_days must be positive")
    index = pd.DatetimeIndex(frame.index)
    slots = (index.hour * 12 + index.minute // 5).to_numpy(dtype=int)
    if len(frame) == 0 or slots[0] != 0:
        raise ValueError("VCOS input must begin at UTC midnight")
    expected_slots = np.arange(len(frame), dtype=int) % BARS_PER_DAY
    if not np.array_equal(slots, expected_slots):
        raise ValueError("VCOS input must be contiguous native 5m UTC bars")

    day_ids = np.arange(len(frame), dtype=int) // BARS_PER_DAY
    day_count = int(day_ids[-1]) + 1
    profiles = np.full((day_count, BARS_PER_DAY), np.nan, dtype=float)
    complete_days = len(frame) // BARS_PER_DAY
    dvol = frame.close.to_numpy(dtype=float) * frame.volume.to_numpy(dtype=float)
    complete_dvol = dvol[: complete_days * BARS_PER_DAY].reshape(
        complete_days, BARS_PER_DAY
    )
    for day in range(seasonal_days, day_count):
        profiles[day] = np.median(
            complete_dvol[day - seasonal_days : day],
            axis=0,
        )
    base_by_day = np.median(profiles, axis=1)
    return SeasonalState(
        profiles=profiles,
        day_ids=day_ids,
        slots=slots,
        base_dvol=base_by_day[day_ids],
    )


def validate_frame(frame: pd.DataFrame) -> None:
    opens = frame.open.to_numpy(dtype=float)
    highs = frame.high.to_numpy(dtype=float)
    lows = frame.low.to_numpy(dtype=float)
    closes = frame.close.to_numpy(dtype=float)
    if bool(np.any(highs < np.maximum(opens, closes))):
        raise ValueError("DOGE input has high below max(open, close)")
    if bool(np.any(lows > np.minimum(opens, closes))):
        raise ValueError("DOGE input has low above min(open, close)")


def capacity_expansion(state: SeasonalState, hold_bars: int) -> np.ndarray:
    if hold_bars <= 0 or hold_bars > BARS_PER_DAY:
        raise ValueError("hold_bars must be in [1, 288]")
    entry_slots = (np.arange(BARS_PER_DAY, dtype=int) + 1) % BARS_PER_DAY
    future_slots = np.stack(
        [
            (entry_slots + offset) % BARS_PER_DAY
            for offset in range(hold_bars)
        ],
        axis=1,
    )
    past_slots = np.stack(
        [
            (entry_slots - offset) % BARS_PER_DAY
            for offset in range(1, hold_bars + 1)
        ],
        axis=1,
    )
    future = state.profiles[:, future_slots].sum(axis=2)
    past = state.profiles[:, past_slots].sum(axis=2)
    ratios = np.full_like(future, np.nan)
    np.divide(future, past, out=ratios, where=past > 0.0)
    return ratios[state.day_ids, state.slots]


def build_bucket_features(
    frame: pd.DataFrame,
    state: SeasonalState,
    bucket_size: float,
) -> BucketFeatures:
    """Find the two newest whole-bar volume buckets with prefix-sum searches."""
    if not math.isfinite(bucket_size) or bucket_size <= 0.0:
        raise ValueError("bucket_size must be finite and positive")
    count = len(frame)
    opens = frame.open.to_numpy(dtype=float)
    highs = frame.high.to_numpy(dtype=float)
    lows = frame.low.to_numpy(dtype=float)
    closes = frame.close.to_numpy(dtype=float)
    volumes = frame.volume.to_numpy(dtype=float)
    dvol = closes * volumes
    prefix_dvol = np.r_[0.0, np.cumsum(dvol)]
    thresholds = bucket_size * state.base_dvol

    newest_start = np.full(count, -1, dtype=int)
    rows = np.flatnonzero(np.isfinite(thresholds) & (thresholds > 0.0))
    newest_targets = prefix_dvol[rows + 1] - thresholds[rows]
    newest_start[rows] = np.searchsorted(
        prefix_dvol,
        newest_targets,
        side="right",
    ) - 1
    newest_start = np.minimum(newest_start, np.arange(count, dtype=int))
    older_end = newest_start - 1
    older_start = np.full(count, -1, dtype=int)
    candidate_rows = rows[older_end[rows] >= 1]
    older_targets = (
        prefix_dvol[newest_start[candidate_rows]] - thresholds[candidate_rows]
    )
    older_start[candidate_rows] = np.searchsorted(
        prefix_dvol,
        older_targets,
        side="right",
    ) - 1
    older_start = np.minimum(older_start, older_end)

    newest_span = np.arange(count, dtype=int) - newest_start + 1
    older_span = newest_start - older_start
    valid = (
        (newest_start >= 1)
        & (older_start >= 1)
        & (newest_span <= MAX_SPAN)
        & (older_span <= MAX_SPAN)
    )

    invalid_bar = (volumes <= 0.0) | (highs <= lows)
    invalid_prefix = np.r_[0, np.cumsum(invalid_bar.astype(int))]
    valid_rows = np.flatnonzero(valid)
    newest_invalid = (
        invalid_prefix[valid_rows + 1]
        - invalid_prefix[newest_start[valid_rows]]
    )
    older_invalid = (
        invalid_prefix[older_end[valid_rows] + 1]
        - invalid_prefix[older_start[valid_rows]]
    )
    valid[valid_rows] &= (newest_invalid == 0) & (older_invalid == 0)
    valid_rows = np.flatnonzero(valid)

    returns = np.zeros(count, dtype=float)
    returns[1:] = np.diff(np.log(closes))
    squared_prefix = np.r_[0.0, np.cumsum(returns * returns)]
    newest_rv = np.zeros(count, dtype=float)
    older_rv = np.zeros(count, dtype=float)
    newest_rv[valid_rows] = np.sqrt(
        squared_prefix[valid_rows + 1]
        - squared_prefix[newest_start[valid_rows]]
    )
    older_rv[valid_rows] = np.sqrt(
        squared_prefix[older_end[valid_rows] + 1]
        - squared_prefix[older_start[valid_rows]]
    )
    valid[valid_rows] &= (
        (newest_rv[valid_rows] > 0.0) & (older_rv[valid_rows] > 0.0)
    )
    valid_rows = np.flatnonzero(valid)

    newest_return = np.zeros(count, dtype=float)
    older_return = np.zeros(count, dtype=float)
    newest_return[valid_rows] = np.log(
        closes[valid_rows] / opens[newest_start[valid_rows]]
    )
    older_return[valid_rows] = np.log(
        closes[older_end[valid_rows]] / opens[older_start[valid_rows]]
    )
    newest_direction = np.sign(newest_return)
    older_direction = np.sign(older_return)
    valid[valid_rows] &= (
        (newest_direction[valid_rows] != 0.0)
        & (newest_direction[valid_rows] == older_direction[valid_rows])
    )
    valid_rows = np.flatnonzero(valid)

    coherence = np.zeros(count, dtype=float)
    coherence[valid_rows] = np.minimum(
        np.abs(newest_return[valid_rows]) / newest_rv[valid_rows],
        np.abs(older_return[valid_rows]) / older_rv[valid_rows],
    )
    range_max = _RangeMaximum(np.abs(returns))
    newest_jump = np.zeros(count, dtype=float)
    older_jump = np.zeros(count, dtype=float)
    newest_jump[valid_rows] = range_max.query(
        newest_start[valid_rows], valid_rows
    )
    older_jump[valid_rows] = range_max.query(
        older_start[valid_rows], older_end[valid_rows]
    )
    jump_share = np.zeros(count, dtype=float)
    jump_share[valid_rows] = np.maximum(
        newest_jump[valid_rows] / newest_rv[valid_rows],
        older_jump[valid_rows] / older_rv[valid_rows],
    )
    direction = np.where(valid, newest_direction, 0.0)
    return BucketFeatures(
        direction=direction,
        coherence=coherence,
        jump_share=jump_share,
        newest_span=np.where(valid, newest_span, 0),
        older_span=np.where(valid, older_span, 0),
        valid=valid,
    )


def build_fixed_time_features(frame: pd.DataFrame, bucket_bars: int) -> BucketFeatures:
    """Wall-clock ablation using two fixed, adjacent bar buckets."""
    if bucket_bars <= 0 or bucket_bars > MAX_SPAN:
        raise ValueError("bucket_bars must be in [1, 72]")
    count = len(frame)
    opens = frame.open.to_numpy(dtype=float)
    highs = frame.high.to_numpy(dtype=float)
    lows = frame.low.to_numpy(dtype=float)
    closes = frame.close.to_numpy(dtype=float)
    volumes = frame.volume.to_numpy(dtype=float)
    rows = np.arange(count, dtype=int)
    newest_start = rows - bucket_bars + 1
    older_end = newest_start - 1
    older_start = older_end - bucket_bars + 1
    valid = older_start >= 1
    invalid_bar = (volumes <= 0.0) | (highs <= lows)
    invalid_prefix = np.r_[0, np.cumsum(invalid_bar.astype(int))]
    valid_rows = np.flatnonzero(valid)
    valid[valid_rows] &= (
        invalid_prefix[valid_rows + 1] - invalid_prefix[older_start[valid_rows]]
        == 0
    )
    valid_rows = np.flatnonzero(valid)

    returns = np.zeros(count, dtype=float)
    returns[1:] = np.diff(np.log(closes))
    squared_prefix = np.r_[0.0, np.cumsum(returns * returns)]
    newest_rv = np.zeros(count, dtype=float)
    older_rv = np.zeros(count, dtype=float)
    newest_rv[valid_rows] = np.sqrt(
        squared_prefix[valid_rows + 1]
        - squared_prefix[newest_start[valid_rows]]
    )
    older_rv[valid_rows] = np.sqrt(
        squared_prefix[older_end[valid_rows] + 1]
        - squared_prefix[older_start[valid_rows]]
    )
    valid[valid_rows] &= (
        (newest_rv[valid_rows] > 0.0) & (older_rv[valid_rows] > 0.0)
    )
    valid_rows = np.flatnonzero(valid)
    newest_return = np.zeros(count, dtype=float)
    older_return = np.zeros(count, dtype=float)
    newest_return[valid_rows] = np.log(
        closes[valid_rows] / opens[newest_start[valid_rows]]
    )
    older_return[valid_rows] = np.log(
        closes[older_end[valid_rows]] / opens[older_start[valid_rows]]
    )
    newest_direction = np.sign(newest_return)
    older_direction = np.sign(older_return)
    valid[valid_rows] &= (
        (newest_direction[valid_rows] != 0.0)
        & (newest_direction[valid_rows] == older_direction[valid_rows])
    )
    valid_rows = np.flatnonzero(valid)
    coherence = np.zeros(count, dtype=float)
    coherence[valid_rows] = np.minimum(
        np.abs(newest_return[valid_rows]) / newest_rv[valid_rows],
        np.abs(older_return[valid_rows]) / older_rv[valid_rows],
    )
    range_max = _RangeMaximum(np.abs(returns))
    newest_jump = np.zeros(count, dtype=float)
    older_jump = np.zeros(count, dtype=float)
    newest_jump[valid_rows] = range_max.query(
        newest_start[valid_rows], valid_rows
    )
    older_jump[valid_rows] = range_max.query(
        older_start[valid_rows], older_end[valid_rows]
    )
    jump_share = np.zeros(count, dtype=float)
    jump_share[valid_rows] = np.maximum(
        newest_jump[valid_rows] / newest_rv[valid_rows],
        older_jump[valid_rows] / older_rv[valid_rows],
    )
    return BucketFeatures(
        direction=np.where(valid, newest_direction, 0.0),
        coherence=coherence,
        jump_share=jump_share,
        newest_span=np.where(valid, bucket_bars, 0),
        older_span=np.where(valid, bucket_bars, 0),
        valid=valid,
    )


def vcos_signal(
    features: BucketFeatures,
    capacity: np.ndarray,
    *,
    coherence_threshold: float,
    capacity_ratio: float,
    jump_share_max: float = JUMP_SHARE_MAX,
) -> np.ndarray:
    signal = np.zeros(len(features.direction), dtype=float)
    accepted = (
        features.valid
        & (features.coherence >= coherence_threshold)
        & (features.jump_share <= jump_share_max)
        & np.isfinite(capacity)
        & (capacity >= capacity_ratio)
    )
    signal[accepted] = features.direction[accepted]
    return signal


def evaluate(
    frame: pd.DataFrame,
    signal: np.ndarray,
    *,
    stage: str,
    seasonal_days: int,
    bucket_size: float,
    coherence_threshold: float,
    capacity_ratio: float,
    hold_bars: int,
) -> VcosTrial:
    values = np.asarray(signal, dtype=float)
    opens = frame.open.to_numpy(dtype=float)
    entries: list[int] = []
    decision = 0
    last_decision = len(frame) - hold_bars - 2
    while decision <= last_decision:
        if values[decision] != 0.0:
            entries.append(decision)
            decision += hold_bars + 1
        else:
            decision += 1
    positions = np.asarray(entries, dtype=int)
    if len(positions):
        directions = values[positions]
        gross = directions * (
            opens[positions + 1 + hold_bars] / opens[positions + 1] - 1.0
        )
        episode_net = gross - ROUND_TRIP_COST
        portfolio_net = TARGET_WEIGHT * episode_net
        entry_times = pd.DatetimeIndex(frame.index[positions + 1])
    else:
        directions = np.empty(0)
        episode_net = np.empty(0)
        portfolio_net = np.empty(0)
        entry_times = pd.DatetimeIndex([])

    pnl_by_bar = np.zeros(len(frame), dtype=float)
    if len(positions):
        pnl_by_bar[positions + 1 + hold_bars] = portfolio_net
    equity = np.cumprod(1.0 + pnl_by_bar)
    equity_with_initial = np.r_[1.0, equity]
    peaks = np.maximum.accumulate(equity_with_initial)
    max_drawdown = float(np.min(equity_with_initial / peaks - 1.0))
    daily = (
        (1.0 + pd.Series(pnl_by_bar, index=frame.index)).resample("1D").prod()
        - 1.0
    )
    deviation = float(daily.std(ddof=1))
    sharpe = (
        float(daily.mean() / deviation * math.sqrt(365.0))
        if deviation > 0.0
        else 0.0
    )
    year_returns = {}
    for year in sorted(set(frame.index.year)):
        mask = entry_times.year == year
        if bool(np.any(mask)):
            year_returns[str(year)] = float(
                np.prod(1.0 + portfolio_net[mask]) - 1.0
            )
    positive = portfolio_net[portfolio_net > 0.0]
    negative = portfolio_net[portfolio_net < 0.0]
    positive_sum = float(positive.sum())
    best_five_share = (
        float(np.sort(positive)[-5:].sum() / positive_sum)
        if positive_sum > 0.0
        else 0.0
    )
    slot_share = 0.0
    if positive_sum > 0.0:
        slots = entry_times.hour * 12 + entry_times.minute // 5
        slot_positive = pd.Series(
            np.maximum(portfolio_net, 0.0), index=slots
        ).groupby(level=0).sum()
        slot_share = float(slot_positive.max() / positive_sum)
    profit_factor = (
        float(positive_sum / abs(float(negative.sum()))) if len(negative) else 0.0
    )
    long = directions > 0.0
    short = directions < 0.0
    return VcosTrial(
        stage=stage,
        seasonal_days=seasonal_days,
        bucket_size=bucket_size,
        coherence_threshold=coherence_threshold,
        capacity_ratio=capacity_ratio,
        hold_bars=hold_bars,
        raw_signals=int(np.count_nonzero(values)),
        episodes=len(positions),
        long_episodes=int(long.sum()),
        short_episodes=int(short.sum()),
        mean_net_bps_on_notional=(
            float(episode_net.mean() * 10_000.0) if len(episode_net) else 0.0
        ),
        total_return=float(equity[-1] - 1.0),
        sharpe=sharpe,
        max_drawdown=max_drawdown,
        win_rate=float(np.mean(episode_net > 0.0)) if len(episode_net) else 0.0,
        profit_factor=profit_factor,
        positive_years=sum(value > 0.0 for value in year_returns.values()),
        active_years=len(year_returns),
        year_returns=year_returns,
        long_pnl=float(portfolio_net[long].sum()),
        short_pnl=float(portfolio_net[short].sum()),
        best_five_positive_pnl_share=best_five_share,
        largest_positive_slot_share=slot_share,
    )


def passes_development_gate(trial: VcosTrial) -> bool:
    return (
        trial.total_return > 0.0
        and trial.sharpe >= 0.50
        and trial.max_drawdown >= -0.20
        and trial.long_pnl > 0.0
        and trial.short_pnl > 0.0
        and trial.episodes >= 30
        and trial.best_five_positive_pnl_share < 0.60
        and trial.largest_positive_slot_share <= 0.35
    )


def select_plateau_center(trials: list[VcosTrial]) -> VcosTrial | None:
    """Choose a topology center only when adjacent structure points pass."""
    q_values = (6.0, 12.0, 24.0)
    z_values = (0.60, 0.80)
    gamma_values = (1.10, 1.25)
    passing = [trial for trial in trials if passes_development_gate(trial)]
    if not passing:
        return None

    def coordinate(trial: VcosTrial) -> tuple[int, int, int]:
        return (
            q_values.index(trial.bucket_size),
            z_values.index(trial.coherence_threshold),
            gamma_values.index(trial.capacity_ratio),
        )

    passing_coordinates = {coordinate(trial) for trial in passing}

    def support(trial: VcosTrial) -> int:
        point = coordinate(trial)
        return sum(
            sum(abs(a - b) for a, b in zip(point, other, strict=True)) == 1
            for other in passing_coordinates
        )

    supported = [trial for trial in passing if support(trial) > 0]
    if not supported:
        return None
    return sorted(
        supported,
        key=lambda trial: (
            -support(trial),
            abs(q_values.index(trial.bucket_size) - 1),
            z_values.index(trial.coherence_threshold),
            gamma_values.index(trial.capacity_ratio),
            trial.bucket_size,
        ),
    )[0]


def run(db_path: Path) -> dict:
    frame = load_bars(db_path)
    validate_frame(frame)
    series = Series(
        "DOGE-USDT-SWAP",
        "5m",
        (pd.DatetimeIndex(frame.index).asi8 // 1_000_000).astype(np.int64),
        frame.open.to_numpy(dtype=float),
        frame.high.to_numpy(dtype=float),
        frame.low.to_numpy(dtype=float),
        frame.close.to_numpy(dtype=float),
        frame.volume.to_numpy(dtype=float),
    )
    states = {28: build_seasonal_state(frame, 28)}
    capacities = {(28, 12): capacity_expansion(states[28], 12)}
    feature_cache: dict[tuple[int, float], BucketFeatures] = {}
    structure_trials = []
    structure_signals: dict[tuple[float, float, float], np.ndarray] = {}
    for bucket_size in (6.0, 12.0, 24.0):
        features = build_bucket_features(frame, states[28], bucket_size)
        feature_cache[(28, bucket_size)] = features
        for coherence, gamma in product((0.60, 0.80), (1.10, 1.25)):
            signal = vcos_signal(
                features,
                capacities[(28, 12)],
                coherence_threshold=coherence,
                capacity_ratio=gamma,
            )
            structure_signals[(bucket_size, coherence, gamma)] = signal
            structure_trials.append(
                evaluate(
                    frame,
                    signal,
                    stage="structure",
                    seasonal_days=28,
                    bucket_size=bucket_size,
                    coherence_threshold=coherence,
                    capacity_ratio=gamma,
                    hold_bars=12,
                )
            )

    center = select_plateau_center(structure_trials)
    refinement_trials: list[VcosTrial] = []
    ablations: dict[str, dict] = {}
    plateau = None
    if center is not None:
        center_q_index = (6.0, 12.0, 24.0).index(center.bucket_size)
        q_neighbors = (6.0, 12.0, 24.0)[
            max(0, center_q_index - 1) : min(3, center_q_index + 2)
        ]
        for seasonal_days in (14, 28):
            if seasonal_days not in states:
                states[seasonal_days] = build_seasonal_state(frame, seasonal_days)
            for hold_bars in (6, 12, 24):
                key = (seasonal_days, hold_bars)
                if key not in capacities:
                    capacities[key] = capacity_expansion(
                        states[seasonal_days], hold_bars
                    )
                for bucket_size in q_neighbors:
                    feature_key = (seasonal_days, bucket_size)
                    if feature_key not in feature_cache:
                        feature_cache[feature_key] = build_bucket_features(
                            frame,
                            states[seasonal_days],
                            bucket_size,
                        )
                    signal = vcos_signal(
                        feature_cache[feature_key],
                        capacities[key],
                        coherence_threshold=center.coherence_threshold,
                        capacity_ratio=center.capacity_ratio,
                    )
                    refinement_trials.append(
                        evaluate(
                            frame,
                            signal,
                            stage="plateau",
                            seasonal_days=seasonal_days,
                            bucket_size=bucket_size,
                            coherence_threshold=center.coherence_threshold,
                            capacity_ratio=center.capacity_ratio,
                            hold_bars=hold_bars,
                        )
                    )

        main_features = feature_cache[(28, center.bucket_size)]
        main_capacity = capacities[(28, 12)]
        valid_spans = np.r_[
            main_features.newest_span[main_features.valid],
            main_features.older_span[main_features.valid],
        ]
        fixed_bars = max(1, min(MAX_SPAN, round(float(valid_spans.mean()))))
        fixed_features = build_fixed_time_features(frame, fixed_bars)
        ablation_signals = {
            "fixed_time_buckets": vcos_signal(
                fixed_features,
                main_capacity,
                coherence_threshold=center.coherence_threshold,
                capacity_ratio=center.capacity_ratio,
            ),
            "no_capacity_gate": vcos_signal(
                main_features,
                main_capacity,
                coherence_threshold=center.coherence_threshold,
                capacity_ratio=-math.inf,
            ),
            "no_jump_share_gate": vcos_signal(
                main_features,
                main_capacity,
                coherence_threshold=center.coherence_threshold,
                capacity_ratio=center.capacity_ratio,
                jump_share_max=math.inf,
            ),
        }
        ablations = {
            name: asdict(
                evaluate(
                    frame,
                    signal,
                    stage=f"ablation:{name}",
                    seasonal_days=28,
                    bucket_size=(
                        float(fixed_bars)
                        if name == "fixed_time_buckets"
                        else center.bucket_size
                    ),
                    coherence_threshold=center.coherence_threshold,
                    capacity_ratio=(
                        0.0 if name == "no_capacity_gate" else center.capacity_ratio
                    ),
                    hold_bars=12,
                )
            )
            for name, signal in ablation_signals.items()
        }
        plateau = {
            "center": asdict(center),
            "neighbor_q_values": list(q_neighbors),
            "refinement_trial_count": len(refinement_trials),
            "passing_refinement_trials": sum(
                passes_development_gate(trial) for trial in refinement_trials
            ),
            "fixed_time_ablation_bucket_bars": fixed_bars,
        }

    trials = [*structure_trials, *refinement_trials]
    ranked = sorted(
        trials,
        key=lambda trial: (
            passes_development_gate(trial),
            trial.positive_years,
            trial.sharpe,
            trial.mean_net_bps_on_notional,
        ),
        reverse=True,
    )
    return {
        "study": "doge-vcos-open-development-v1",
        "mode": "frozen_open_development_on_seen_history_not_confirmation",
        "executed_at": datetime.now(UTC).isoformat(),
        "data": {
            "start": frame.index[0].isoformat(),
            "end_inclusive": frame.index[-1].isoformat(),
            "bars": len(frame),
            "fingerprint": series_fingerprint(series),
            "untouched_holdout": False,
        },
        "execution": {
            "entry": "signal close then next 5m open",
            "exit": "fixed future 5m open",
            "target_weight": TARGET_WEIGHT,
            "cost_bps_per_side": 15.0,
        },
        "search": {
            "structure_trial_count": len(structure_trials),
            "plateau_trial_count": len(refinement_trials),
            "total_trial_count": len(trials),
            "structure_gate_passes": sum(
                passes_development_gate(trial) for trial in structure_trials
            ),
            "plateau_found": center is not None,
            "short_circuit": (
                None
                if center is not None
                else "no adjacent structure points passed the development gate"
            ),
        },
        "plateau": plateau,
        "ablations": ablations,
        "top_10": [asdict(trial) for trial in ranked[:10]],
        "trials": [asdict(trial) for trial in trials],
    }


class _RangeMaximum:
    """Static sparse table for vectorized maximum queries over short intervals."""

    def __init__(self, values: np.ndarray):
        base = np.asarray(values, dtype=float)
        self.tables = [base]
        width = 2
        while width <= MAX_SPAN:
            previous = self.tables[-1]
            half = width // 2
            self.tables.append(np.maximum(previous[:-half], previous[half:]))
            width *= 2

    def query(self, starts: np.ndarray, ends: np.ndarray) -> np.ndarray:
        starts = np.asarray(starts, dtype=int)
        ends = np.asarray(ends, dtype=int)
        lengths = ends - starts + 1
        if bool(np.any(lengths <= 0)) or bool(np.any(lengths > MAX_SPAN)):
            raise ValueError("range query length must be in [1, 72]")
        powers = np.floor(np.log2(lengths)).astype(int)
        result = np.empty(len(starts), dtype=float)
        for power in np.unique(powers):
            mask = powers == power
            width = 1 << int(power)
            table = self.tables[int(power)]
            result[mask] = np.maximum(
                table[starts[mask]],
                table[ends[mask] - width + 1],
            )
        return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("data/cq.db"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/research/doge_vcos_open_development_v1.json"),
    )
    args = parser.parse_args()
    report = run(args.db)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(
        json.dumps(
            {
                "search": report["search"],
                "plateau": report["plateau"],
                "top_10": report["top_10"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
