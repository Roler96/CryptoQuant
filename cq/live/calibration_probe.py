"""Deterministic spot target transitions for engine calibration only.

This is deliberately outside ``cq.strategy``: it expresses no market view and
must never be presented as a research candidate. Repeated targets exercise
inside-band holds; stepped targets force buys, sells and flat transitions
without waiting for a particular price path.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cq.context import Context
from cq.core.types import Intent

CALIBRATION_SEQUENCE_VERSION = 1
CALIBRATION_BAND = 0.01
CALIBRATION_BARS = 200
CALIBRATION_TARGETS = (0.0, 0.0, 0.2, 0.2, 0.4, 0.4, 0.2, 0.2, 0.0, 0.0)


@dataclass
class SpotCalibrationSequence:
    """Repeat the frozen target sequence independently of prices."""

    _count: int = field(default=0, init=False)

    @property
    def name(self) -> str:
        return f"spot-calibration-sequence-v{CALIBRATION_SEQUENCE_VERSION}"

    @property
    def warmup_bars(self) -> int:
        return 1

    @property
    def band(self) -> float:
        return CALIBRATION_BAND

    def on_bar(self, ctx: Context) -> Intent:
        target = CALIBRATION_TARGETS[self._count % len(CALIBRATION_TARGETS)]
        self._count += 1
        return Intent(target=target, reason=self.name)

    def reset(self) -> None:
        self._count = 0

    def snapshot_state(self) -> dict[str, object]:
        return {
            "count": self._count,
            "config": {
                "version": CALIBRATION_SEQUENCE_VERSION,
                "band": CALIBRATION_BAND,
                "targets": list(CALIBRATION_TARGETS),
            },
        }

    def restore_state(self, state: dict[str, object]) -> None:
        count = state.get("count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError(f"invalid calibration checkpoint count {count!r}")
        expected = self.snapshot_state()["config"]
        if state.get("config") != expected:
            raise ValueError("calibration checkpoint configuration does not match")
        self._count = count
