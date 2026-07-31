"""A placeholder strategy for exercising the live path, not for trading views.

`HeartbeatProbe` holds no market opinion. It flips a small target on and off on
a fixed cadence so a paper session produces a steady stream of round trips —
the point is to prove that feed → decision → order → reconcile works, before any
vetted strategy exists to run. It lives here rather than alongside real
strategies on purpose, so it can never be mistaken for a research candidate.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cq.context import Context
from cq.core.types import Intent


@dataclass
class HeartbeatProbe:
    """Alternates between a small long and flat every `period` closed bars."""

    weight: float = 0.02
    period: int = 1
    _count: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if not 0 < self.weight <= 1:
            raise ValueError(f"probe weight must be in (0, 1], got {self.weight}")
        if self.period < 1:
            raise ValueError(f"probe period must be at least 1 bar, got {self.period}")

    @property
    def name(self) -> str:
        return "heartbeat-probe"

    @property
    def warmup_bars(self) -> int:
        return 1

    def on_bar(self, ctx: Context) -> Intent:
        # A square wave off an internal counter: `period` bars long, `period`
        # bars flat, deterministic and independent of price.
        phase = (self._count // self.period) % 2
        self._count += 1
        target = self.weight if phase == 0 else 0.0
        return Intent(target=target, reason="heartbeat")

    def reset(self) -> None:
        self._count = 0

    def snapshot_state(self) -> dict[str, object]:
        """The phase counter needed to continue the square wave after restart."""
        return {"count": self._count, "weight": self.weight, "period": self.period}

    def restore_state(self, state: dict[str, object]) -> None:
        """Restore a checkpoint only when it is valid for this probe."""
        count = state.get("count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError(f"invalid heartbeat checkpoint count {count!r}")
        if state.get("weight") != self.weight or state.get("period") != self.period:
            raise ValueError("heartbeat checkpoint configuration does not match this probe")
        self._count = count
