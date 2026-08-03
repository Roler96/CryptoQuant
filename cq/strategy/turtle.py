"""Classic Turtle channel breakout strategy.

The strategy enters on a breakout of the prior entry channel, exits on the
shorter prior exit channel, and protects a new unit with a fixed ATR-based
stop.  It deliberately does not pyramid: the engine expresses exposure as a
target weight, so adding Turtle units would require portfolio/equity feedback
that is not part of the causal strategy context.
"""

from __future__ import annotations

import math

import numpy as np

from cq.context import Context
from cq.core.types import Intent


class TurtleTrend:
    """Trade Donchian breakouts with a shorter exit channel and a 2N stop."""

    def __init__(
        self,
        entry_lookback: int = 20,
        exit_lookback: int = 10,
        atr_lookback: int = 20,
        stop_atr: float = 2.0,
        target: float = 1.0,
        allow_short: bool = True,
    ):
        for name, value in (
            ("entry_lookback", entry_lookback),
            ("exit_lookback", exit_lookback),
            ("atr_lookback", atr_lookback),
        ):
            if value < 1:
                raise ValueError(f"{name} must be at least 1, got {value}")
        if exit_lookback > entry_lookback:
            raise ValueError("exit_lookback cannot exceed entry_lookback")
        if not math.isfinite(stop_atr) or stop_atr <= 0:
            raise ValueError(f"stop_atr must be finite and positive, got {stop_atr}")
        if not math.isfinite(target) or target <= 0:
            raise ValueError(f"target must be finite and positive, got {target}")

        self._entry_lookback = entry_lookback
        self._exit_lookback = exit_lookback
        self._atr_lookback = atr_lookback
        self._stop_atr = stop_atr
        self._weight = target
        self._allow_short = allow_short
        self._target = 0.0
        self._stop: float | None = None

    @property
    def name(self) -> str:
        direction = "long-short" if self._allow_short else "long-only"
        return (
            f"turtle-{self._entry_lookback}-{self._exit_lookback}"
            f"-atr{self._atr_lookback}-stop{self._stop_atr:g}"
            f"-{direction}-w{self._weight:g}"
        )

    @property
    def warmup_bars(self) -> int:
        # Channels exclude the deciding bar; ATR needs a preceding close for
        # each true-range observation.
        return max(
            self._entry_lookback + 1,
            self._exit_lookback + 1,
            self._atr_lookback + 1,
        )

    def reset(self) -> None:
        self._target = 0.0
        self._stop = None

    def on_bar(self, ctx: Context) -> Intent:
        bar = ctx.bar
        entry_highs = ctx.high(self._entry_lookback + 1)[:-1]
        entry_lows = ctx.low(self._entry_lookback + 1)[:-1]
        exit_highs = ctx.high(self._exit_lookback + 1)[:-1]
        exit_lows = ctx.low(self._exit_lookback + 1)[:-1]
        atr = self._atr(ctx)

        if self._target > 0:
            stop_hit = self._stop is not None and bar.low <= self._stop
            channel_exit = bar.low <= float(exit_lows.min())
            if stop_hit or channel_exit:
                return self._flatten("long-stop" if stop_hit else "long-exit")
        elif self._target < 0:
            stop_hit = self._stop is not None and bar.high >= self._stop
            channel_exit = bar.high >= float(exit_highs.max())
            if stop_hit or channel_exit:
                return self._flatten("short-stop" if stop_hit else "short-exit")
        else:
            long_breakout = bar.high > float(entry_highs.max())
            short_breakout = bar.low < float(entry_lows.min())
            # With OHLC bars the order of two same-bar breakouts is unknowable.
            # Staying flat avoids choosing the favourable direction in hindsight.
            if long_breakout and not short_breakout:
                self._target = self._weight
                self._stop = max(np.nextafter(0.0, 1.0), bar.close - self._stop_atr * atr)
                return self._intent("long-entry")
            if short_breakout and not long_breakout and self._allow_short:
                self._target = -self._weight
                self._stop = bar.close + self._stop_atr * atr
                return self._intent("short-entry")

        return self._intent("hold")

    def _atr(self, ctx: Context) -> float:
        highs = ctx.high(self._atr_lookback + 1)
        lows = ctx.low(self._atr_lookback + 1)
        closes = ctx.close(self._atr_lookback + 1)
        true_ranges = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(abs(highs[1:] - closes[:-1]), abs(lows[1:] - closes[:-1])),
        )
        return float(true_ranges.mean())

    def _flatten(self, event: str) -> Intent:
        self._target = 0.0
        self._stop = None
        return self._intent(event)

    def _intent(self, event: str) -> Intent:
        return Intent(
            target=self._target,
            stop_loss=self._stop,
            reason=f"{self.name}:{event}",
        )
