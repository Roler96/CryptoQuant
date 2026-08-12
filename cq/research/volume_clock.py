"""Causal volume-clock order-splitting continuation research strategy."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from cq.context import Context
from cq.core.clock import duration_ms
from cq.core.types import FLAT, Intent

BARS_PER_DAY = 288
FIVE_MINUTES_MS = 300_000


@dataclass(frozen=True)
class VolumeClockConfig:
    seasonal_days: int = 28
    bucket_size: float = 12.0
    coherence_threshold: float = 0.60
    capacity_ratio: float = 1.10
    hold_bars: int = 12
    max_span: int = 72
    jump_share_max: float = 0.75
    target_weight: float = 0.25
    evaluation_start_ms: int = -(2**63)
    evaluation_end_ms: int = 2**63 - 1

    def __post_init__(self) -> None:
        if self.seasonal_days <= 0:
            raise ValueError("seasonal_days must be positive")
        if not math.isfinite(self.bucket_size) or self.bucket_size <= 0.0:
            raise ValueError("bucket_size must be finite and positive")
        if not 0.0 < self.coherence_threshold <= 1.0:
            raise ValueError("coherence_threshold must be in (0, 1]")
        if not math.isfinite(self.capacity_ratio) or self.capacity_ratio <= 0.0:
            raise ValueError("capacity_ratio must be finite and positive")
        if self.hold_bars <= 0 or self.hold_bars > BARS_PER_DAY:
            raise ValueError("hold_bars must be in [1, 288]")
        if self.max_span <= 0:
            raise ValueError("max_span must be positive")
        if not 0.0 < self.jump_share_max <= 1.0:
            raise ValueError("jump_share_max must be in (0, 1]")
        if not 0.0 < self.target_weight <= 1.0:
            raise ValueError("target_weight must be in (0, 1]")
        if self.evaluation_start_ms >= self.evaluation_end_ms:
            raise ValueError("evaluation window must be non-empty")


class VolumeClockStrategy:
    """Build two causal volume-time buckets and follow their shared direction."""

    name = "doge-volume-clock-order-splitting-continuation"

    def __init__(self, config: VolumeClockConfig | None = None):
        self.config = config or VolumeClockConfig()
        self._remaining = 0
        self._target = 0.0

    @property
    def warmup_bars(self) -> int:
        # One additional partial day makes D complete UTC days available at
        # every possible slot of the first evaluated day.
        return (self.config.seasonal_days + 1) * BARS_PER_DAY

    def reset(self) -> None:
        self._remaining = 0
        self._target = 0.0

    def on_bar(self, ctx: Context) -> Intent:
        config = self.config
        if ctx.now < config.evaluation_start_ms:
            self.reset()
            return FLAT

        if self._remaining > 1:
            self._remaining -= 1
            return Intent(target=self._target, reason="volume-clock-hold")
        if self._remaining == 1:
            self.reset()
            return Intent(target=0.0, reason="volume-clock-time-exit")

        bar_ms = duration_ms(ctx.primary.timeframe)
        if bar_ms != FIVE_MINUTES_MS:
            raise ValueError("VolumeClockStrategy requires native 5m bars")
        exit_time = ctx.decision_time + config.hold_bars * bar_ms
        if exit_time >= config.evaluation_end_ms:
            return FLAT

        current_slot = (ctx.now // FIVE_MINUTES_MS) % BARS_PER_DAY
        required = config.seasonal_days * BARS_PER_DAY + current_slot + 1
        timestamps = ctx.primary.timestamps(required)
        if not bool(np.all(np.diff(timestamps) == FIVE_MINUTES_MS)):
            return FLAT
        opens = ctx.open(required)
        highs = ctx.high(required)
        lows = ctx.low(required)
        closes = ctx.close(required)
        volumes = ctx.volume(required)
        history_end = config.seasonal_days * BARS_PER_DAY
        historical_dvol = (
            closes[:history_end] * volumes[:history_end]
        ).reshape(config.seasonal_days, BARS_PER_DAY)
        seasonal_dvol = np.median(historical_dvol, axis=0)
        target = volume_clock_target(
            timestamps=timestamps,
            opens=opens,
            highs=highs,
            lows=lows,
            closes=closes,
            volumes=volumes,
            seasonal_dvol=seasonal_dvol,
            config=config,
        )
        if target == 0.0:
            return FLAT
        self._remaining = config.hold_bars
        self._target = target * config.target_weight
        return Intent(target=self._target, reason="volume-clock-continuation")


def volume_clock_target(
    *,
    timestamps: np.ndarray,
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    volumes: np.ndarray,
    seasonal_dvol: np.ndarray,
    config: VolumeClockConfig,
) -> float:
    """Return the shared direction of two coherent, non-jump volume buckets."""
    ts = np.asarray(timestamps, dtype=np.int64)
    open_values = np.asarray(opens, dtype=float)
    high_values = np.asarray(highs, dtype=float)
    low_values = np.asarray(lows, dtype=float)
    close_values = np.asarray(closes, dtype=float)
    volume_values = np.asarray(volumes, dtype=float)
    seasonal = np.asarray(seasonal_dvol, dtype=float)
    columns = (ts, open_values, high_values, low_values, close_values, volume_values)
    if any(values.ndim != 1 for values in columns):
        raise ValueError("bar columns must be one-dimensional")
    lengths = {len(values) for values in columns}
    if len(lengths) != 1:
        raise ValueError("bar columns must have equal lengths")
    if len(ts) < 2 * config.max_span + 1:
        raise ValueError("not enough bars for two maximum-span buckets")
    if seasonal.shape != (BARS_PER_DAY,):
        raise ValueError("seasonal_dvol must contain 288 UTC slots")
    prices = np.column_stack((open_values, high_values, low_values, close_values))
    if not np.isfinite(prices).all() or bool(np.any(prices <= 0.0)):
        raise ValueError("prices must be finite and positive")
    if bool(np.any(high_values < np.maximum(open_values, close_values))):
        raise ValueError("high must be at least max(open, close)")
    if bool(np.any(low_values > np.minimum(open_values, close_values))):
        raise ValueError("low must be at most min(open, close)")
    if not np.isfinite(volume_values).all() or bool(np.any(volume_values < 0.0)):
        raise ValueError("volumes must be finite and non-negative")
    if not np.isfinite(seasonal).all() or bool(np.any(seasonal <= 0.0)):
        return 0.0
    if not bool(np.all(np.diff(ts) == FIVE_MINUTES_MS)):
        return 0.0

    base_dvol = float(np.median(seasonal))
    if not math.isfinite(base_dvol) or base_dvol <= 0.0:
        return 0.0
    dvol = close_values * volume_values / base_dvol
    newest = _backward_bucket(dvol, len(dvol) - 1, config)
    if newest is None:
        return 0.0
    older = _backward_bucket(dvol, newest[0] - 1, config)
    if older is None:
        return 0.0

    newest_stats = _bucket_statistics(
        newest, open_values, high_values, low_values, close_values, volume_values
    )
    older_stats = _bucket_statistics(
        older, open_values, high_values, low_values, close_values, volume_values
    )
    if newest_stats is None or older_stats is None:
        return 0.0
    newest_return, newest_rv, newest_jump_share = newest_stats
    older_return, older_rv, older_jump_share = older_stats
    newest_direction = math.copysign(1.0, newest_return) if newest_return else 0.0
    older_direction = math.copysign(1.0, older_return) if older_return else 0.0
    if newest_direction == 0.0 or newest_direction != older_direction:
        return 0.0
    if abs(newest_return) / newest_rv < config.coherence_threshold:
        return 0.0
    if abs(older_return) / older_rv < config.coherence_threshold:
        return 0.0
    if max(newest_jump_share, older_jump_share) > config.jump_share_max:
        return 0.0

    current_slot = (int(ts[-1]) // FIVE_MINUTES_MS) % BARS_PER_DAY
    entry_slot = (current_slot + 1) % BARS_PER_DAY
    future_capacity = sum(
        seasonal[(entry_slot + offset) % BARS_PER_DAY]
        for offset in range(config.hold_bars)
    )
    past_capacity = sum(
        seasonal[(entry_slot - offset) % BARS_PER_DAY]
        for offset in range(1, config.hold_bars + 1)
    )
    if past_capacity <= 0.0:
        return 0.0
    if future_capacity / past_capacity < config.capacity_ratio:
        return 0.0
    return newest_direction


def _backward_bucket(
    normalized_dvol: np.ndarray,
    end: int,
    config: VolumeClockConfig,
) -> tuple[int, int] | None:
    if end < 1:
        return None
    cumulative = 0.0
    lower = max(1, end - config.max_span + 1)
    for start in range(end, lower - 1, -1):
        value = float(normalized_dvol[start])
        if not math.isfinite(value) or value <= 0.0:
            return None
        cumulative += value
        if cumulative >= config.bucket_size:
            return start, end
    return None


def _bucket_statistics(
    bucket: tuple[int, int],
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    volumes: np.ndarray,
) -> tuple[float, float, float] | None:
    start, end = bucket
    if bool(np.any(volumes[start : end + 1] <= 0.0)):
        return None
    if bool(np.any(highs[start : end + 1] <= lows[start : end + 1])):
        return None
    returns = np.log(closes[start : end + 1] / closes[start - 1 : end])
    rv = float(math.sqrt(float(np.dot(returns, returns))))
    bucket_return = float(math.log(float(closes[end]) / float(opens[start])))
    if not math.isfinite(rv) or rv <= 0.0 or not math.isfinite(bucket_return):
        return None
    jump_share = float(np.max(np.abs(returns)) / rv)
    return bucket_return, rv, jump_share
