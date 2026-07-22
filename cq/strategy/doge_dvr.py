"""Frozen DOGE spot directional-variance tail-risk strategy."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np

from cq.context import Context
from cq.core.types import Intent


@dataclass(frozen=True)
class DogeDvrConfig:
    """The pre-2024 selected DVR-T20 configuration."""

    horizon: int = 28
    entry_share: float = 0.60
    exit_share: float = 0.45
    trail_drawdown: float = 0.20
    size: float = 0.25

    def __post_init__(self) -> None:
        if self.horizon < 2:
            raise ValueError("horizon must be at least two bars")
        if not 0 <= self.exit_share < self.entry_share <= 1:
            raise ValueError("DVR thresholds must satisfy 0 <= exit < entry <= 1")
        if not 0 < self.trail_drawdown < 1:
            raise ValueError("trail_drawdown must be in (0, 1)")
        if not 0 < self.size <= 1:
            raise ValueError("spot size must be in (0, 1]")


class DogeDvrTail20:
    """Quarter-weight long/cash exposure in an upside-variance regime.

    A close-confirmed 20% fall from the highest close exits the position and
    disarms re-entry until the original directional-variance state has reset.
    Signals are daily; the engine executes every target at the next daily open.
    """

    def __init__(self, config: DogeDvrConfig | None = None):
        self.config = config or DogeDvrConfig()
        self._target = 0.0
        self._peak_close = 0.0
        self._armed = True

    @property
    def name(self) -> str:
        c = self.config
        return (
            f"doge-dvr-tail{c.trail_drawdown * 100:g}"
            f"-h{c.horizon}-size{c.size:g}"
        )

    @property
    def warmup_bars(self) -> int:
        return self.config.horizon + 1

    def reset(self) -> None:
        self._target = 0.0
        self._peak_close = 0.0
        self._armed = True

    def snapshot_state(self) -> dict[str, object]:
        return {
            "target": self._target,
            "peak_close": self._peak_close,
            "armed": self._armed,
            "config": asdict(self.config),
        }

    def restore_state(self, state: dict[str, object]) -> None:
        if state.get("config") != asdict(self.config):
            raise ValueError("DOGE DVR checkpoint configuration does not match")
        raw_target = state.get("target")
        raw_peak = state.get("peak_close")
        raw_armed = state.get("armed")
        if (
            isinstance(raw_target, bool)
            or not isinstance(raw_target, (int, float))
            or float(raw_target) not in (0.0, self.config.size)
        ):
            raise ValueError("invalid DOGE DVR checkpoint target")
        if (
            isinstance(raw_peak, bool)
            or not isinstance(raw_peak, (int, float))
            or not math.isfinite(float(raw_peak))
            or float(raw_peak) < 0
        ):
            raise ValueError("invalid DOGE DVR checkpoint peak")
        if not isinstance(raw_armed, bool):
            raise ValueError("invalid DOGE DVR checkpoint armed flag")
        target = float(raw_target)
        peak = float(raw_peak)
        if target == 0.0 and peak != 0.0:
            raise ValueError("flat DOGE DVR checkpoint cannot carry a peak")
        if target > 0.0 and peak <= 0.0:
            raise ValueError("long DOGE DVR checkpoint must carry a peak")
        self._target = target
        self._peak_close = peak
        self._armed = raw_armed

    def on_bar(self, ctx: Context) -> Intent:
        c = self.config
        close = ctx.close(self.warmup_bars)
        log_returns = np.diff(np.log(close))
        total_variance = float(np.sum(np.square(log_returns)))
        upside_variance = float(
            np.sum(np.square(np.maximum(log_returns, 0.0)))
        )
        variance_share = (
            upside_variance / total_variance if total_variance > 0 else 0.5
        )
        momentum = float(math.log(close[-1] / close[0]))
        current = float(close[-1])
        original_exit = variance_share <= c.exit_share or momentum <= 0

        if self._target > 0:
            self._peak_close = max(self._peak_close, current)
            trail_exit = current <= self._peak_close * (1.0 - c.trail_drawdown)
            if original_exit or trail_exit:
                self._target = 0.0
                self._peak_close = 0.0
                self._armed = bool(original_exit)
        elif not self._armed:
            if original_exit:
                self._armed = True
        elif variance_share >= c.entry_share and momentum > 0:
            self._target = c.size
            self._peak_close = current

        return Intent(target=self._target, reason=self.name)
