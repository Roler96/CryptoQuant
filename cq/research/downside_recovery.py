"""Causal DOGE downside-shock partial-recovery research strategy."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

import numpy as np

from cq.context import Context
from cq.core.clock import duration_ms
from cq.core.types import FLAT, Intent


@dataclass(frozen=True)
class DownsideRecoveryConfig:
    shock_window: int = 4
    volatility_window: int = 7 * 24 * 12
    shock_z: float = 5.5
    recovery_floor: float = 0.30
    recovery_ceiling: float = 0.80
    hold_bars: int = 12
    target_weight: float = 0.25
    evaluation_start_ms: int = -(2**63)
    evaluation_end_ms: int = 2**63 - 1

    def __post_init__(self) -> None:
        if self.shock_window < 2:
            raise ValueError("shock_window must be at least two")
        if self.volatility_window <= self.shock_window:
            raise ValueError("volatility_window must exceed shock_window")
        if not math.isfinite(self.shock_z) or self.shock_z <= 0.0:
            raise ValueError("shock_z must be finite and positive")
        if not 0.0 < self.recovery_floor < self.recovery_ceiling <= 1.0:
            raise ValueError("recovery bounds must satisfy 0 < floor < ceiling <= 1")
        if self.hold_bars <= 0:
            raise ValueError("hold_bars must be positive")
        if not 0.0 < self.target_weight <= 1.0:
            raise ValueError("target_weight must be in (0, 1]")
        if self.evaluation_start_ms >= self.evaluation_end_ms:
            raise ValueError("evaluation window must be non-empty")


class DownsideRecoveryStrategy:
    name = "doge-downside-shock-recovery"

    def __init__(self, config: DownsideRecoveryConfig | None = None):
        self.config = config or DownsideRecoveryConfig()
        self._remaining = 0
        self._reference: deque[float] = deque(maxlen=self.config.volatility_window)
        self._recent: deque[float] = deque(maxlen=self.config.shock_window)
        self._reference_sum = 0.0
        self._reference_sum_sq = 0.0
        self._last_return = 0.0
        self._last_index: int | None = None

    @property
    def warmup_bars(self) -> int:
        return self.config.volatility_window + 2

    def reset(self) -> None:
        self._remaining = 0
        self._reference.clear()
        self._recent.clear()
        self._reference_sum = 0.0
        self._reference_sum_sq = 0.0
        self._last_return = 0.0
        self._last_index = None

    def on_bar(self, ctx: Context) -> Intent:
        config = self.config
        if ctx.now < config.evaluation_start_ms:
            self.reset()
            return FLAT

        current_return = self._advance_statistics(ctx)

        if self._remaining > 1:
            self._remaining -= 1
            return Intent(target=config.target_weight, reason="downside-recovery-hold")
        if self._remaining == 1:
            self.reset()
            return Intent(target=0.0, reason="downside-recovery-time-exit")

        bar_ms = duration_ms(ctx.primary.timeframe)
        entry_time = ctx.decision_time
        exit_time = entry_time + config.hold_bars * bar_ms
        if exit_time >= config.evaluation_end_ms:
            return FLAT

        target = self._rolling_target(ctx, current_return)
        if target == 0.0:
            return FLAT
        self._remaining = config.hold_bars
        return Intent(
            target=target * config.target_weight,
            reason="downside-shock-partial-recovery",
        )

    def _advance_statistics(self, ctx: Context) -> float:
        config = self.config
        if self._last_index is None or ctx.index != self._last_index + 1:
            closes = ctx.close(config.volatility_window + 2)
            returns = np.diff(np.log(closes))
            reference = returns[:-1]
            self._reference = deque(
                (float(value) for value in reference),
                maxlen=config.volatility_window,
            )
            self._recent = deque(
                (float(value) for value in reference[-config.shock_window :]),
                maxlen=config.shock_window,
            )
            self._reference_sum = float(np.sum(reference))
            self._reference_sum_sq = float(np.dot(reference, reference))
            current_return = float(returns[-1])
        else:
            oldest = self._reference.popleft()
            newest = self._last_return
            self._reference.append(newest)
            self._recent.append(newest)
            self._reference_sum += newest - oldest
            self._reference_sum_sq += newest * newest - oldest * oldest
            closes = ctx.close(2)
            current_return = float(math.log(float(closes[-1]) / float(closes[-2])))
        self._last_return = current_return
        self._last_index = ctx.index
        return current_return

    def _rolling_target(self, ctx: Context, current_return: float) -> float:
        config = self.config
        volumes = ctx.volume(config.shock_window + 1)
        if bool(np.any(volumes <= 0.0)):
            return 0.0
        count = config.volatility_window
        variance = (
            self._reference_sum_sq - self._reference_sum * self._reference_sum / count
        ) / (count - 1)
        sigma = math.sqrt(max(0.0, variance))
        if not math.isfinite(sigma) or sigma <= 0.0:
            return 0.0
        prior_shock = float(sum(self._recent))
        return _target_from_statistics(prior_shock, current_return, sigma, config)


def signal_target(
    closes: np.ndarray,
    volumes: np.ndarray,
    config: DownsideRecoveryConfig,
) -> float:
    """Return long after an extreme downside shock begins a bounded recovery."""
    values = np.asarray(closes, dtype=float)
    volume_values = np.asarray(volumes, dtype=float)
    expected = config.volatility_window + 2
    if len(values) != expected:
        raise ValueError(f"expected {expected} closes, got {len(values)}")
    if len(volume_values) != expected:
        raise ValueError(f"expected {expected} volumes, got {len(volume_values)}")
    if not np.isfinite(values).all() or bool(np.any(values <= 0.0)):
        raise ValueError("closes must be finite and positive")
    if not np.isfinite(volume_values).all() or bool(np.any(volume_values < 0.0)):
        raise ValueError("volumes must be finite and non-negative")
    if bool(np.any(volume_values[-(config.shock_window + 1) :] <= 0.0)):
        return 0.0

    returns = np.diff(np.log(values))
    reference = returns[-(config.volatility_window + 1) : -1]
    sigma = float(np.std(reference, ddof=1))
    if not math.isfinite(sigma) or sigma <= 0.0:
        return 0.0
    prior_shock = float(np.sum(returns[-(config.shock_window + 1) : -1]))
    current_return = float(returns[-1])
    return _target_from_statistics(prior_shock, current_return, sigma, config)


def _target_from_statistics(
    prior_shock: float,
    current_return: float,
    sigma: float,
    config: DownsideRecoveryConfig,
) -> float:
    if prior_shock >= 0.0 or current_return <= 0.0:
        return 0.0
    shock_z = abs(prior_shock) / (sigma * math.sqrt(float(config.shock_window)))
    recovery_fraction = current_return / abs(prior_shock)
    if shock_z < config.shock_z:
        return 0.0
    if not config.recovery_floor <= recovery_fraction <= config.recovery_ceiling:
        return 0.0
    return 1.0
