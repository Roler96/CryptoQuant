"""Causal URA signal, fixed-hold strategy, and schedule construction."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from cq.context import Context, Series
from cq.core.types import FLAT, Intent
from cq.research.ura.data import HOUR_MS


@dataclass(frozen=True)
class UraConfig:
    lookback_hours: int = 24
    upper_boundary: float = 0.75
    lower_boundary: float = 0.25
    minimum_upper_share: float = 0.50
    maximum_lower_share: float = 0.25
    hold_hours: int = 24
    target_weight: float = 0.25
    evaluation_start_ms: int = -(2**63)
    evaluation_end_ms: int = 2**63 - 1

    def __post_init__(self) -> None:
        if self.lookback_hours <= 0 or self.hold_hours <= 0:
            raise ValueError("lookback and hold must be positive")
        if not 0 <= self.lower_boundary < self.upper_boundary <= 1:
            raise ValueError("range boundaries must be ordered inside [0, 1]")
        if not 0 <= self.minimum_upper_share <= 1:
            raise ValueError("minimum upper share must be inside [0, 1]")
        if not 0 <= self.maximum_lower_share <= 1:
            raise ValueError("maximum lower share must be inside [0, 1]")
        if not 0 < self.target_weight <= 1:
            raise ValueError("target weight must be inside (0, 1]")


@dataclass(frozen=True)
class SignalEvent:
    decision_index: int
    entry_index: int
    exit_index: int
    upper_share: float
    lower_share: float
    current_location: float


class UraStrategy:
    """Shared-engine implementation of the frozen main rule."""

    name = "ura-v1"

    def __init__(self, config: UraConfig | None = None):
        self.config = config or UraConfig()
        self._remaining = 0

    @property
    def warmup_bars(self) -> int:
        return self.config.lookback_hours + 1

    def reset(self) -> None:
        self._remaining = 0

    def on_bar(self, ctx: Context) -> Intent:
        if self._remaining > 1:
            self._remaining -= 1
            return Intent(target=self.config.target_weight, reason="ura-hold")
        if self._remaining == 1:
            self._remaining = 0
            return Intent(target=0.0, reason="ura-time-exit")

        entry_time = ctx.decision_time
        exit_time = entry_time + self.config.hold_hours * HOUR_MS
        if (
            entry_time < self.config.evaluation_start_ms
            or exit_time >= self.config.evaluation_end_ms
        ):
            return FLAT

        closes = ctx.close(self.config.lookback_hours + 1)
        volumes = ctx.volume(self.config.lookback_hours + 1)
        signal = signal_values(closes[:-1], closes[-1], volumes, self.config)
        if signal is None:
            return FLAT
        self._remaining = self.config.hold_hours
        return Intent(target=self.config.target_weight, reason="ura-entry")


def signal_values(
    reference_closes: np.ndarray,
    current_close: float,
    known_volumes: np.ndarray,
    config: UraConfig,
) -> tuple[float, float, float] | None:
    if len(reference_closes) != config.lookback_hours:
        raise ValueError("reference window length disagrees with lookback")
    if len(known_volumes) != config.lookback_hours + 1:
        raise ValueError("volume window must include reference and decision bars")
    if bool(np.any(known_volumes <= 0.0)):
        return None

    low = float(np.min(reference_closes))
    high = float(np.max(reference_closes))
    if high == low:
        return None
    locations = (reference_closes - low) / (high - low)
    upper_share = float(np.count_nonzero(locations >= config.upper_boundary)) / len(
        reference_closes
    )
    lower_share = float(np.count_nonzero(locations <= config.lower_boundary)) / len(
        reference_closes
    )
    current_location = (float(current_close) - low) / (high - low)
    if (
        upper_share >= config.minimum_upper_share
        and lower_share <= config.maximum_lower_share
        and current_location >= config.upper_boundary
        and current_close <= high
    ):
        return upper_share, lower_share, current_location
    return None


def build_schedule(series: Series, config: UraConfig | None = None) -> list[SignalEvent]:
    """Generate accepted events without looking at entry/exit volume or returns."""
    config = config or UraConfig()
    events: list[SignalEvent] = []
    blocked_through_decision = -1
    last_decision = len(series) - config.hold_hours - 2
    for decision_index in range(config.lookback_hours, last_decision + 1):
        if decision_index <= blocked_through_decision:
            continue
        entry_index = decision_index + 1
        exit_index = entry_index + config.hold_hours
        entry_time = int(series.ts[entry_index])
        exit_time = int(series.ts[exit_index])
        if entry_time < config.evaluation_start_ms or exit_time >= config.evaluation_end_ms:
            continue
        start = decision_index - config.lookback_hours
        signal = signal_values(
            series.close[start:decision_index],
            float(series.close[decision_index]),
            series.volume[start : decision_index + 1],
            config,
        )
        if signal is None:
            continue
        events.append(
            SignalEvent(
                decision_index,
                entry_index,
                exit_index,
                signal[0],
                signal[1],
                signal[2],
            )
        )
        blocked_through_decision = exit_index - 1
    return events


def condition_funnel(series: Series, config: UraConfig | None = None) -> dict[str, int]:
    """Return-only-free counts after each frozen predicate, in protocol order."""
    config = config or UraConfig()
    counts = {
        "eligible_decisions": 0,
        "positive_known_volume": 0,
        "nonconstant_reference_range": 0,
        "minimum_upper_share": 0,
        "maximum_lower_share": 0,
        "current_upper_location": 0,
        "raw_signals": 0,
        "accepted_schedule": 0,
    }
    last_decision = len(series) - config.hold_hours - 2
    for decision_index in range(config.lookback_hours, last_decision + 1):
        entry_index = decision_index + 1
        exit_index = entry_index + config.hold_hours
        entry_time = int(series.ts[entry_index])
        exit_time = int(series.ts[exit_index])
        if entry_time < config.evaluation_start_ms or exit_time >= config.evaluation_end_ms:
            continue
        counts["eligible_decisions"] += 1
        start = decision_index - config.lookback_hours
        volumes = series.volume[start : decision_index + 1]
        if bool(np.any(volumes <= 0.0)):
            continue
        counts["positive_known_volume"] += 1
        reference = series.close[start:decision_index]
        low = float(np.min(reference))
        high = float(np.max(reference))
        if high == low:
            continue
        counts["nonconstant_reference_range"] += 1
        locations = (reference - low) / (high - low)
        upper_share = float(np.count_nonzero(locations >= config.upper_boundary)) / len(
            reference
        )
        if upper_share < config.minimum_upper_share:
            continue
        counts["minimum_upper_share"] += 1
        lower_share = float(np.count_nonzero(locations <= config.lower_boundary)) / len(
            reference
        )
        if lower_share > config.maximum_lower_share:
            continue
        counts["maximum_lower_share"] += 1
        current = float(series.close[decision_index])
        current_location = (current - low) / (high - low)
        if current_location < config.upper_boundary:
            continue
        counts["current_upper_location"] += 1
        if current > high:
            continue
        counts["raw_signals"] += 1
    counts["accepted_schedule"] = len(build_schedule(series, config))
    return counts
