"""Causal coherent-path exhaustion reversal research strategy."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from cq.context import Context
from cq.core.clock import duration_ms
from cq.core.types import FLAT, Intent


@dataclass(frozen=True)
class CoherentPathConfig:
    window_bars: int = 18
    efficiency_threshold: float = 0.78
    hold_bars: int = 12
    target_weight: float = 0.25
    evaluation_start_ms: int = -(2**63)
    evaluation_end_ms: int = 2**63 - 1

    def __post_init__(self) -> None:
        if self.window_bars < 2:
            raise ValueError("window_bars must be at least two")
        if not 0.0 < self.efficiency_threshold <= 1.0:
            raise ValueError("efficiency_threshold must be in (0, 1]")
        if self.hold_bars <= 0:
            raise ValueError("hold_bars must be positive")
        if not 0.0 < self.target_weight <= 1.0:
            raise ValueError("target_weight must be in (0, 1]")
        if self.evaluation_start_ms >= self.evaluation_end_ms:
            raise ValueError("evaluation window must be non-empty")


class CoherentPathStrategy:
    name = "doge-coherent-path-exhaustion-reversal"

    def __init__(self, config: CoherentPathConfig | None = None):
        self.config = config or CoherentPathConfig()
        self._remaining = 0
        self._target = 0.0

    @property
    def warmup_bars(self) -> int:
        return self.config.window_bars + 1

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
            return Intent(target=self._target, reason="coherent-path-hold")
        if self._remaining == 1:
            self.reset()
            return Intent(target=0.0, reason="coherent-path-time-exit")

        bar_ms = duration_ms(ctx.primary.timeframe)
        entry_time = ctx.decision_time
        exit_time = entry_time + config.hold_bars * bar_ms
        if exit_time >= config.evaluation_end_ms:
            return FLAT

        target = signal_target(
            ctx.close(config.window_bars + 1),
            ctx.volume(config.window_bars + 1),
            config,
        )
        if target == 0.0:
            return FLAT
        self._remaining = config.hold_bars
        self._target = target * config.target_weight
        return Intent(target=self._target, reason="coherent-path-exhaustion")


def signal_target(
    closes: np.ndarray, volumes: np.ndarray, config: CoherentPathConfig
) -> float:
    """Return the reversal target from one fully closed price path."""
    values = np.asarray(closes, dtype=float)
    volume_values = np.asarray(volumes, dtype=float)
    expected = config.window_bars + 1
    if len(values) != expected:
        raise ValueError(f"expected {expected} closes, got {len(values)}")
    if len(volume_values) != expected:
        raise ValueError(f"expected {expected} volumes, got {len(volume_values)}")
    if not np.isfinite(values).all() or bool(np.any(values <= 0.0)):
        raise ValueError("closes must be finite and positive")
    if not np.isfinite(volume_values).all() or bool(np.any(volume_values < 0.0)):
        raise ValueError("volumes must be finite and non-negative")
    if bool(np.any(volume_values <= 0.0)):
        return 0.0

    returns = np.diff(np.log(values))
    gross_path = float(np.sum(np.abs(returns)))
    if not math.isfinite(gross_path) or gross_path <= 0.0:
        return 0.0
    net_path = float(np.sum(returns))
    efficiency = abs(net_path) / gross_path
    if efficiency < config.efficiency_threshold or net_path == 0.0:
        return 0.0
    return -1.0 if net_path > 0.0 else 1.0
