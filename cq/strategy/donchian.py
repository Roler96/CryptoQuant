"""Donchian channel breakout, long/short symmetric.

Written from parameters rather than from the previous implementation, which
is deliberately not consulted during this rebuild. The logic is the textbook
one: enter on a break of the entry channel, leave on a break of the shorter
exit channel, and treat both directions the same way.

The channels exclude the current bar. Including it makes the long entry
condition unsatisfiable — a bar's close never exceeds its own high — so the
strategy would simply never trade, which is the kind of silent nothing that
looks like a flat equity curve rather than an error.
"""

from __future__ import annotations

import numpy as np

from cq.context import Context
from cq.core.types import Intent


class DonchianTrend:
    """Breakout trend following on a single instrument.

    Parameters follow the candidate this project has carried since 2026-07:
    a 120-bar entry channel and a 60-bar exit channel on 4h bars.

    `long_only` makes the strategy skip the short entry, so it never asks to
    hold a negative target. That is what lets it run on spot, where the engine
    refuses a short outright rather than clamp it to flat behind the caller's
    back. The clamp still happens — it just happens here, as a declared mode
    that the strategy name records, instead of silently inside the market spec.
    A long-only run and a long/short run are different strategies and must not
    be mistaken for one another, so the name carries the distinction.
    """

    def __init__(
        self,
        entry_lookback: int = 120,
        exit_lookback: int = 60,
        size: float = 1.0,
        long_only: bool = False,
    ):
        if entry_lookback < 2 or exit_lookback < 2:
            raise ValueError("lookbacks must be at least 2 bars")
        if size <= 0:
            raise ValueError("size must be positive")
        self.entry_lookback = entry_lookback
        self.exit_lookback = exit_lookback
        self.size = size
        self.long_only = long_only
        self._target = 0.0

    @property
    def name(self) -> str:
        suffix = "-long" if self.long_only else ""
        return f"donchian-{self.entry_lookback}-{self.exit_lookback}{suffix}"

    @property
    def warmup_bars(self) -> int:
        # One extra bar because the channels look strictly backwards.
        return max(self.entry_lookback, self.exit_lookback) + 1

    def reset(self) -> None:
        self._target = 0.0

    def on_bar(self, ctx: Context) -> Intent:
        close = float(ctx.close(1)[-1])

        entry_high, entry_low = self._channel(ctx, self.entry_lookback)
        exit_high, exit_low = self._channel(ctx, self.exit_lookback)

        if self._target == 0.0:
            if close > entry_high:
                self._target = self.size
            elif close < entry_low and not self.long_only:
                self._target = -self.size
        elif self._target > 0.0:
            if close < exit_low:
                self._target = 0.0
        elif close > exit_high:
            self._target = 0.0

        return Intent(target=self._target, reason=self.name)

    def _channel(self, ctx: Context, lookback: int) -> tuple[float, float]:
        """Highest high and lowest low of the `lookback` bars before this one."""
        highs = ctx.high(lookback + 1)[:-1]
        lows = ctx.low(lookback + 1)[:-1]
        return float(np.max(highs)), float(np.min(lows))
