"""Causal jump-diffusion permanent-jump confirmation strategy."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from cq.context import Context
from cq.core.clock import duration_ms
from cq.core.types import FLAT, Intent


@dataclass(frozen=True)
class JumpDiffusionConfig:
    diffusion_window: int = 288
    jump_z: float = 5.0
    body_ratio: float = 0.60
    volume_ratio: float = 2.0
    confirm_bars: int = 2
    retention: float = 0.80
    hold_bars: int = 24
    target_weight: float = 0.25
    evaluation_start_ms: int = -(2**63)
    evaluation_end_ms: int = 2**63 - 1

    def __post_init__(self) -> None:
        if self.diffusion_window < 3:
            raise ValueError("diffusion_window must be at least three")
        if not math.isfinite(self.jump_z) or self.jump_z <= 0.0:
            raise ValueError("jump_z must be finite and positive")
        if not 0.0 < self.body_ratio <= 1.0:
            raise ValueError("body_ratio must be in (0, 1]")
        if not math.isfinite(self.volume_ratio) or self.volume_ratio <= 0.0:
            raise ValueError("volume_ratio must be finite and positive")
        if self.confirm_bars <= 0:
            raise ValueError("confirm_bars must be positive")
        if not 0.0 < self.retention <= 1.0:
            raise ValueError("retention must be in (0, 1]")
        if self.hold_bars <= 0:
            raise ValueError("hold_bars must be positive")
        if not 0.0 < self.target_weight <= 1.0:
            raise ValueError("target_weight must be in (0, 1]")
        if self.evaluation_start_ms >= self.evaluation_end_ms:
            raise ValueError("evaluation window must be non-empty")


class JumpDiffusionStrategy:
    name = "doge-jump-diffusion-confirmation"

    def __init__(self, config: JumpDiffusionConfig | None = None):
        self.config = config or JumpDiffusionConfig()
        self._remaining = 0
        self._target = 0.0

    @property
    def warmup_bars(self) -> int:
        return self.config.diffusion_window + self.config.confirm_bars + 2

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
            return Intent(target=self._target, reason="jump-confirmation-hold")
        if self._remaining == 1:
            self.reset()
            return Intent(target=0.0, reason="jump-confirmation-time-exit")

        bar_ms = duration_ms(ctx.primary.timeframe)
        entry_time = ctx.decision_time
        exit_time = entry_time + config.hold_bars * bar_ms
        if exit_time >= config.evaluation_end_ms:
            return FLAT

        lookback = self.warmup_bars
        target = confirmed_jump_target(
            ctx.high(lookback),
            ctx.low(lookback),
            ctx.close(lookback),
            ctx.volume(lookback),
            config,
        )
        if target == 0.0:
            return FLAT
        self._remaining = config.hold_bars
        self._target = target * config.target_weight
        return Intent(target=self._target, reason="permanent-jump-confirmed")


def confirmed_jump_target(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    volumes: np.ndarray,
    config: JumpDiffusionConfig,
) -> float:
    """Return jump direction when an earlier statistical jump remains retained."""
    high_values = np.asarray(highs, dtype=float)
    low_values = np.asarray(lows, dtype=float)
    close_values = np.asarray(closes, dtype=float)
    volume_values = np.asarray(volumes, dtype=float)
    expected = config.diffusion_window + config.confirm_bars + 2
    for name, values in (
        ("highs", high_values),
        ("lows", low_values),
        ("closes", close_values),
        ("volumes", volume_values),
    ):
        if len(values) != expected:
            raise ValueError(f"expected {expected} {name}, got {len(values)}")
        if not np.isfinite(values).all():
            raise ValueError(f"{name} must be finite")
    if bool(np.any(high_values <= 0.0)) or bool(np.any(low_values <= 0.0)):
        raise ValueError("highs and lows must be positive")
    if bool(np.any(close_values <= 0.0)):
        raise ValueError("closes must be positive")
    if bool(np.any(volume_values < 0.0)):
        raise ValueError("volumes must be non-negative")
    if bool(np.any(high_values < low_values)):
        raise ValueError("highs must not be below lows")

    n = config.diffusion_window
    jump_bar = n + 1
    if volume_values[jump_bar] <= 0.0 or high_values[jump_bar] <= low_values[jump_bar]:
        return 0.0

    returns = np.diff(np.log(close_values))
    adjacent_products = np.abs(returns[1:n]) * np.abs(returns[: n - 1])
    bipower_variation = math.pi / 2.0 * float(np.mean(adjacent_products))
    diffusion_scale = math.sqrt(max(bipower_variation, 0.0))
    jump_return = float(returns[n])
    if diffusion_scale <= 0.0 or jump_return == 0.0:
        return 0.0
    if abs(jump_return) / diffusion_scale < config.jump_z:
        return 0.0

    jump_range = math.log(high_values[jump_bar] / low_values[jump_bar])
    if jump_range <= 0.0 or abs(jump_return) / jump_range < config.body_ratio:
        return 0.0

    dvol = close_values * volume_values
    prior_dvol = dvol[1 : n + 1]
    if bool(np.any(prior_dvol <= 0.0)):
        return 0.0
    baseline_dvol = float(np.median(prior_dvol))
    if baseline_dvol <= 0.0 or dvol[jump_bar] / baseline_dvol < config.volume_ratio:
        return 0.0

    direction = math.copysign(1.0, jump_return)
    pre_jump_log = math.log(close_values[n])
    jump_log = math.log(close_values[jump_bar])
    confirmed_log = math.log(close_values[-1])
    retention = direction * (confirmed_log - pre_jump_log) / abs(jump_return)
    if retention < config.retention:
        return 0.0

    post_returns = returns[n + 1 :]
    post_noise = math.sqrt(float(np.dot(post_returns, post_returns)))
    if direction * (confirmed_log - jump_log) < -0.5 * post_noise:
        return 0.0
    return direction
