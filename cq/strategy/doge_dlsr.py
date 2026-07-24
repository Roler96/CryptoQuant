"""Frozen DOGE spot 5m downside-liquidity-sweep-reclaim strategy (DLSR v1).

Literal translation of `docs/research/doge-5m/DOWNSIDE_LIQUIDITY_SWEEP_RECLAIM_
PROTOCOL_2026-07-24.md`, judged FIT by the 2026-07-24 pre-registration audit.

The strategy emits the framework's ordinary `Intent(target, reason)`. DLSR
requires the signal's immediately following 5m open, while the framework
normally carries rejected pending targets forward. Zero-volume entry bars are
therefore consumed by the strategy at their close, and any timestamp gap
aborts the run rather than silently approximating the frozen protocol. This
keeps the shared engine untouched and makes a gapped DLSR result impossible.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Literal, cast

import numpy as np

from cq.context import Context
from cq.core.types import Intent

# The protocol is native-5m only; every contiguity rule below is in these units.
BAR_MS = 300_000

_Phase = Literal["flat", "pending_entry", "holding", "pending_exit"]


@dataclass(frozen=True)
class DogeDlsrConfig:
    """One frozen DLSR version.

    Only `range_mult`, `volume_mult` and `hold_bars` vary across the seven
    pre-declared versions; everything else is a frozen constant of the family
    and changing it is a new protocol, not a parameter choice.
    """

    range_mult: float = 3.0
    volume_mult: float = 3.0
    hold_bars: int = 12

    floor_bars: int = 12
    baseline_bars: int = 2016
    sweep_depth_mult: float = 0.5
    close_location_min: float = 0.75
    target_weight: float = 0.25
    cooldown_bars: int = 144

    def __post_init__(self) -> None:
        if self.range_mult <= 0 or self.volume_mult <= 0:
            raise ValueError("shell multipliers must be positive")
        if self.hold_bars <= 0 or self.floor_bars <= 0 or self.baseline_bars <= 0:
            raise ValueError("bar windows must be positive")
        if not 0.0 < self.target_weight <= 1.0:
            raise ValueError("target weight must be in (0, 1]")
        if not 0.0 <= self.close_location_min <= 1.0:
            raise ValueError("close location threshold must be in [0, 1]")
        if self.cooldown_bars < 0:
            raise ValueError("cooldown cannot be negative")


# The pre-declared family: main plus six one-axis neighbours. Nothing outside
# this table may be searched, and only main can be promoted.
FROZEN_VERSIONS: dict[str, DogeDlsrConfig] = {
    "main": DogeDlsrConfig(),
    "range2": DogeDlsrConfig(range_mult=2.0),
    "range4": DogeDlsrConfig(range_mult=4.0),
    "volume2": DogeDlsrConfig(volume_mult=2.0),
    "volume4": DogeDlsrConfig(volume_mult=4.0),
    "hold6": DogeDlsrConfig(hold_bars=6),
    "hold24": DogeDlsrConfig(hold_bars=24),
}

FAMILY_TRIALS = len(FROZEN_VERSIONS)


def _optional_non_negative_int(value: object, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"invalid DLSR checkpoint {name} {value!r}")
    return value


def _checkpoint_count(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"invalid DLSR checkpoint {name} {value!r}")
    return value


class DogeDlsr:
    """Buy a same-bar reclaim of a swept prior-hour low; hold one fixed hour.

    The full entry condition, exit schedule, cooldown and void rules are the
    protocol's; nothing here is tunable at run time. The class re-derives its
    own fill outcomes from bar data (see module docstring), so its phase is a
    deterministic function of the bars seen so far and two runs over the same
    series cannot diverge.
    """

    def __init__(self, config: DogeDlsrConfig | None = None):
        self.config = config or DogeDlsrConfig()
        if self.config not in FROZEN_VERSIONS.values():
            raise ValueError(
                "DLSR configuration is not one of the seven pre-registered versions"
            )
        self.reset()

    @property
    def name(self) -> str:
        c = self.config
        return f"doge-dlsr-v1-r{c.range_mult:g}-v{c.volume_mult:g}-h{c.hold_bars}"

    @property
    def warmup_bars(self) -> int:
        # The baseline window needs `baseline_bars` closed bars strictly before
        # the signal bar, so the first decidable bar is index `baseline_bars`.
        return self.config.baseline_bars + 1

    @property
    def accepted_events(self) -> int:
        return self._accepted_events

    @property
    def voided_entries(self) -> int:
        return self._voided_entries

    @property
    def completed_episodes(self) -> int:
        return self._completed_episodes

    # ---- lifecycle ----------------------------------------------------

    def reset(self) -> None:
        self._phase: _Phase = "flat"
        self._entry_index: int | None = None
        self._planned_entry_ts: int | None = None
        self._cooldown_start_ts: int | None = None
        self._prev_ts: int | None = None
        self._accepted_events = 0
        self._voided_entries = 0
        self._completed_episodes = 0

    def snapshot_state(self) -> dict[str, object]:
        return {
            "config": asdict(self.config),
            "phase": self._phase,
            "entry_index": self._entry_index,
            "planned_entry_ts": self._planned_entry_ts,
            "cooldown_start_ts": self._cooldown_start_ts,
            "prev_ts": self._prev_ts,
            "accepted_events": self._accepted_events,
            "voided_entries": self._voided_entries,
            "completed_episodes": self._completed_episodes,
        }

    def restore_state(self, state: dict[str, object]) -> None:
        if state.get("config") != asdict(self.config):
            raise ValueError("DLSR checkpoint configuration does not match")
        phase = state.get("phase")
        if phase not in ("flat", "pending_entry", "holding", "pending_exit"):
            raise ValueError(f"invalid DLSR checkpoint phase {phase!r}")

        entry_index = _optional_non_negative_int(state.get("entry_index"), "entry_index")
        planned_entry_ts = _optional_non_negative_int(
            state.get("planned_entry_ts"), "planned_entry_ts"
        )
        cooldown_start_ts = _optional_non_negative_int(
            state.get("cooldown_start_ts"), "cooldown_start_ts"
        )
        prev_ts = _optional_non_negative_int(state.get("prev_ts"), "prev_ts")
        if phase == "holding" and entry_index is None:
            raise ValueError("DLSR holding checkpoint has no entry index")
        if phase == "pending_entry" and planned_entry_ts is None:
            raise ValueError("DLSR pending-entry checkpoint has no planned timestamp")

        self._phase = cast(_Phase, phase)
        self._entry_index = entry_index
        self._planned_entry_ts = planned_entry_ts
        self._cooldown_start_ts = cooldown_start_ts
        self._prev_ts = prev_ts
        self._accepted_events = _checkpoint_count(
            state.get("accepted_events"), "accepted_events"
        )
        self._voided_entries = _checkpoint_count(
            state.get("voided_entries"), "voided_entries"
        )
        self._completed_episodes = _checkpoint_count(
            state.get("completed_episodes"), "completed_episodes"
        )

    # ---- per-bar decision ---------------------------------------------

    def on_bar(self, ctx: Context) -> Intent:
        if ctx.primary.inst_id != "DOGE-USDT":
            raise ValueError(
                f"DLSR is frozen for DOGE-USDT spot; got {ctx.primary.inst_id!r}"
            )
        if ctx.primary.timeframe != "5m":
            raise ValueError(
                f"DLSR is a native-5m protocol; got timeframe {ctx.primary.timeframe!r}"
            )
        bar = ctx.bar
        index = ctx.index
        if self._prev_ts is None:
            observed_ts = ctx.primary.timestamps(index + 1)
            contiguous = bool(np.all(np.diff(observed_ts) == BAR_MS))
        else:
            contiguous = bar.ts - self._prev_ts == BAR_MS
        if not contiguous:
            raise ValueError(
                "DLSR requires a contiguous native 5m series; "
                "a timestamp gap is present in the observed history"
            )

        if self._phase == "pending_entry":
            self._resolve_entry(index, bar.volume)
            if self._phase == "holding":
                # The entry bar is itself the first complete held bar, so hold
                # completion must be checked on it too, not first on the next.
                self._check_hold_complete(index)
        elif self._phase == "holding":
            self._check_hold_complete(index)
        elif self._phase == "pending_exit":
            self._resolve_exit(bar.ts, bar.volume)

        if (
            self._phase == "flat"
            and self._may_signal(index, ctx.decision_time)
            and self._signal(ctx)
        ):
            self._phase = "pending_entry"
            self._planned_entry_ts = ctx.decision_time
            self._accepted_events += 1

        self._prev_ts = bar.ts
        target = (
            self.config.target_weight
            if self._phase in ("pending_entry", "holding")
            else 0.0
        )
        return Intent(target=target, reason=self.name)

    # ---- state transitions --------------------------------------------

    def _resolve_entry(
        self,
        index: int,
        volume: float,
    ) -> None:
        """Decide what happened to the order planned for this bar's open."""
        if volume > 0:
            self._phase = "holding"
            self._entry_index = index
            self._planned_entry_ts = None
            return
        # The broker rejected the zero-volume entry. Returning target 0 below
        # overwrites its pending target, so it cannot chase the next open.
        self._void_entry()

    def _void_entry(self) -> None:
        planned = self._planned_entry_ts
        if planned is None:  # pragma: no cover - state invariant
            raise RuntimeError("voided DLSR entry has no planned timestamp")
        self._phase = "flat"
        self._voided_entries += 1
        self._cooldown_start_ts = planned
        self._planned_entry_ts = None

    def _check_hold_complete(self, index: int) -> None:
        entry = self._entry_index
        if entry is None:  # pragma: no cover - unreachable by construction
            raise RuntimeError("holding without an entry index")
        if index - entry + 1 >= self.config.hold_bars:
            self._phase = "pending_exit"

    def _resolve_exit(self, ts: int, volume: float) -> None:
        """Decide whether the exit planned for this bar's open was filled."""
        if volume <= 0:
            # Untradeable exit bar: the target stays 0 and the engine retries at
            # the next open; the delay is part of the episode by protocol.
            return
        self._completed_episodes += 1
        self._cooldown_start_ts = ts
        self._phase = "flat"
        self._entry_index = None

    # ---- signal -------------------------------------------------------

    def _may_signal(self, index: int, planned_entry_ts: int) -> bool:
        if index < self.config.baseline_bars:
            return False
        cooldown = self._cooldown_start_ts
        return (
            cooldown is None
            or planned_entry_ts - cooldown >= self.config.cooldown_bars * BAR_MS
        )

    def _signal(self, ctx: Context) -> bool:
        """The frozen shell + reclaim geometry, on a fully valid window."""
        c = self.config
        window = c.baseline_bars + 1

        ts = ctx.primary.timestamps(window)
        if not bool(np.all(np.diff(ts) == BAR_MS)):
            return False

        opens = ctx.open(window)
        highs = ctx.high(window)
        lows = ctx.low(window)
        closes = ctx.close(window)
        volumes = ctx.volume(window)

        finite = (
            np.isfinite(opens)
            & np.isfinite(highs)
            & np.isfinite(lows)
            & np.isfinite(closes)
            & np.isfinite(volumes)
        )
        body_low = np.minimum(opens, closes)
        body_high = np.maximum(opens, closes)
        legal = (
            finite
            & (lows > 0.0)
            & (lows <= body_low)
            & (body_high <= highs)
            & (volumes >= 0.0)
        )
        if not bool(np.all(legal)):
            return False

        baseline_ranges = np.log(highs[:-1] / lows[:-1])
        range_med = float(np.median(baseline_ranges))
        volume_med = float(np.median(volumes[:-1]))
        if range_med <= 0.0 or volume_med <= 0.0:
            return False

        floor = float(np.min(lows[-1 - c.floor_bars : -1]))
        low = float(lows[-1])
        high = float(highs[-1])
        close = float(closes[-1])
        volume = float(volumes[-1])

        if volume <= 0.0 or low >= floor:
            return False
        if math.log(floor / low) < c.sweep_depth_mult * range_med:
            return False
        if math.log(high / low) < c.range_mult * range_med:
            return False
        if volume < c.volume_mult * volume_med:
            return False
        if close <= floor:
            return False
        close_location = (close - low) / (high - low)
        return close_location >= c.close_location_min
