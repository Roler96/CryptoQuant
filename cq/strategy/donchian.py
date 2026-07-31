"""A single-channel Donchian breakout — the reference strategy for the engine.

Market- and timeframe-agnostic: it only reads `Context`, so the same instance
backtests spot or swap, any instrument, any bar size. The target it emits is
always in {0.0, 1.0}, which is valid on spot markets (no short) without any
special-casing.

Holding between the two bands requires remembering the last emitted target —
`on_bar` alone cannot express "unchanged", since a `Context` only exposes the
past, never the strategy's own prior decision.
"""

from __future__ import annotations

from cq.context import Context
from cq.core.types import Intent


class DonchianTrend:
    """Long when price breaks above the N-bar high, flat when it breaks below the N-bar low."""

    def __init__(self, lookback: int = 20):
        if lookback < 1:
            raise ValueError(f"lookback must be at least 1, got {lookback}")
        self._lookback = lookback
        self._target = 0.0

    @property
    def name(self) -> str:
        return f"donchian-trend-{self._lookback}"

    @property
    def warmup_bars(self) -> int:
        # `on_bar` reads `lookback` prior closes plus the current one.
        return self._lookback + 1

    def reset(self) -> None:
        self._target = 0.0

    def on_bar(self, ctx: Context) -> Intent:
        window = ctx.close(self._lookback + 1)[:-1]
        close = ctx.bar.close
        if close > window.max():
            self._target = 1.0
        elif close < window.min():
            self._target = 0.0
        return Intent(target=self._target, reason=self.name)
