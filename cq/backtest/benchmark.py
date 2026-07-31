"""Reference portfolios reported alongside every strategy backtest."""

from __future__ import annotations

from cq.context import Context
from cq.core.types import Intent


class BuyAndHold:
    """Enter a full long position at the evaluation start and never exit."""

    @property
    def name(self) -> str:
        return "buy-and-hold"

    @property
    def warmup_bars(self) -> int:
        return 0

    def reset(self) -> None:
        pass

    def on_bar(self, ctx: Context) -> Intent:
        return Intent(target=1.0, reason=self.name)
