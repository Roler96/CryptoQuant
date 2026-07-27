"""Frozen BTC/ETH 1h impulse-continuation strategy (BIC-Majors v1).

Literal translation of `docs/superpowers/specs/2026-07-27-btc-intraday-design.md`
section 5. A bar whose absolute return clears the trailing 168-bar 99th
percentile is an impulse; the position is taken *with* it and held twelve hours.

BTC is the opposite of DOGE at this scale. DOGE's DIR buys a down-impulse
expecting the liquidation cascade to overshoot and revert; here a down-impulse
keeps falling, so the rule is signed by the impulse and trades both tails. That
symmetry is not cosmetic — it centres the null distribution on zero, which is
how a single-asset timing rule escapes the power wall.

The strategy re-asserts its target every bar rather than trusting the engine's
pending queue, and any timestamp gap aborts the run instead of quietly
approximating the frozen rule. Both are engine-observed facts about sparse
event strategies, not defensive habits.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal, cast

import numpy as np

from cq.context import Context
from cq.core.types import Intent

# The protocol is native-1h only; every contiguity rule below is in these units.
BAR_MS = 3_600_000

FROZEN_INSTRUMENTS = ("BTC-USDT-SWAP", "ETH-USDT-SWAP")

_Phase = Literal["flat", "pending_entry", "holding", "pending_exit"]


@dataclass(frozen=True)
class BicConfig:
    """One frozen BIC version.

    Only `quantile`, `hold_bars`, `baseline_bars` and `cooldown_bars` vary
    across the seven pre-declared versions; `target_weight` is a frozen
    constant of the family and changing it is a new protocol.
    """

    quantile: float = 0.99
    hold_bars: int = 12
    baseline_bars: int = 168
    cooldown_bars: int = 12

    target_weight: float = 0.25

    def __post_init__(self) -> None:
        if not 0.5 < self.quantile < 1.0:
            raise ValueError("quantile must be in (0.5, 1)")
        if self.hold_bars <= 0 or self.baseline_bars <= 0:
            raise ValueError("bar windows must be positive")
        if self.cooldown_bars < 0:
            raise ValueError("cooldown cannot be negative")
        if not 0.0 < self.target_weight <= 1.0:
            raise ValueError("target weight must be in (0, 1]")


# The pre-declared family: main plus six one-axis neighbours. Nothing outside
# this table may be searched, and only main can be promoted.
FROZEN_VERSIONS: dict[str, BicConfig] = {
    "main": BicConfig(),
    "q995": BicConfig(quantile=0.995),
    "q999": BicConfig(quantile=0.999),
    "hold8": BicConfig(hold_bars=8),
    "hold24": BicConfig(hold_bars=24),
    "trail336": BicConfig(baseline_bars=336),
    "cool24": BicConfig(cooldown_bars=24),
}

FAMILY_TRIALS = len(FROZEN_VERSIONS)


def _optional_non_negative_int(value: object, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"invalid BIC checkpoint {name} {value!r}")
    return value


def _checkpoint_count(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"invalid BIC checkpoint {name} {value!r}")
    return value


class BicMajors:
    """Trade with a 1h impulse on BTC or ETH perpetuals; hold twelve hours.

    One instance trades one instrument. The two legs of the candidate are two
    instances with identical configuration — no parameter is adjusted per
    asset, because the ETH replication only carries evidential weight while
    that stays true.
    """

    def __init__(self, config: BicConfig | None = None, *, inst_id: str = "BTC-USDT-SWAP"):
        self.config = config or BicConfig()
        if self.config not in FROZEN_VERSIONS.values():
            raise ValueError(
                "BIC configuration is not one of the seven pre-registered versions"
            )
        if inst_id not in FROZEN_INSTRUMENTS:
            raise ValueError(
                f"BIC is frozen for {FROZEN_INSTRUMENTS}; got {inst_id!r}"
            )
        self.inst_id = inst_id
        self.reset()

    @property
    def name(self) -> str:
        c = self.config
        asset = self.inst_id.split("-")[0].lower()
        return f"bic-majors-v1-{asset}-q{c.quantile:g}-h{c.hold_bars}"

    @property
    def warmup_bars(self) -> int:
        # Returns over `baseline_bars` bars strictly before the signal bar need
        # one extra close to difference against, plus the signal bar itself.
        return self.config.baseline_bars + 2

    @property
    def accepted_events(self) -> int:
        return self._accepted_events

    @property
    def voided_entries(self) -> int:
        return self._voided_entries

    @property
    def completed_episodes(self) -> int:
        return self._completed_episodes

    @property
    def long_events(self) -> int:
        return self._long_events

    @property
    def short_events(self) -> int:
        return self._short_events

    # ---- lifecycle ----------------------------------------------------

    def reset(self) -> None:
        self._phase: _Phase = "flat"
        self._side: float = 0.0
        self._entry_index: int | None = None
        self._planned_entry_ts: int | None = None
        self._cooldown_start_ts: int | None = None
        self._prev_ts: int | None = None
        self._accepted_events = 0
        self._voided_entries = 0
        self._completed_episodes = 0
        self._long_events = 0
        self._short_events = 0

    def snapshot_state(self) -> dict[str, object]:
        return {
            "config": asdict(self.config),
            "inst_id": self.inst_id,
            "phase": self._phase,
            "side": self._side,
            "entry_index": self._entry_index,
            "planned_entry_ts": self._planned_entry_ts,
            "cooldown_start_ts": self._cooldown_start_ts,
            "prev_ts": self._prev_ts,
            "accepted_events": self._accepted_events,
            "voided_entries": self._voided_entries,
            "completed_episodes": self._completed_episodes,
            "long_events": self._long_events,
            "short_events": self._short_events,
        }

    def restore_state(self, state: dict[str, object]) -> None:
        if state.get("config") != asdict(self.config):
            raise ValueError("BIC checkpoint configuration does not match")
        if state.get("inst_id") != self.inst_id:
            raise ValueError("BIC checkpoint instrument does not match")
        phase = state.get("phase")
        if phase not in ("flat", "pending_entry", "holding", "pending_exit"):
            raise ValueError(f"invalid BIC checkpoint phase {phase!r}")
        side = state.get("side")
        if side not in (-1.0, 0.0, 1.0):
            raise ValueError(f"invalid BIC checkpoint side {side!r}")
        if phase in ("pending_entry", "holding", "pending_exit") and side == 0.0:
            raise ValueError("BIC checkpoint has a position phase with no side")

        entry_index = _optional_non_negative_int(state.get("entry_index"), "entry_index")
        planned_entry_ts = _optional_non_negative_int(
            state.get("planned_entry_ts"), "planned_entry_ts"
        )
        cooldown_start_ts = _optional_non_negative_int(
            state.get("cooldown_start_ts"), "cooldown_start_ts"
        )
        prev_ts = _optional_non_negative_int(state.get("prev_ts"), "prev_ts")
        if phase == "holding" and entry_index is None:
            raise ValueError("BIC holding checkpoint has no entry index")
        if phase == "pending_entry" and planned_entry_ts is None:
            raise ValueError("BIC pending-entry checkpoint has no planned timestamp")

        self._phase = cast(_Phase, phase)
        self._side = float(cast(float, side))
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
        self._long_events = _checkpoint_count(state.get("long_events"), "long_events")
        self._short_events = _checkpoint_count(state.get("short_events"), "short_events")

    # ---- per-bar decision ---------------------------------------------

    def on_bar(self, ctx: Context) -> Intent:
        if ctx.primary.inst_id != self.inst_id:
            raise ValueError(
                f"BIC instance is bound to {self.inst_id!r}; "
                f"got {ctx.primary.inst_id!r}"
            )
        if ctx.primary.timeframe != "1h":
            raise ValueError(
                f"BIC is a native-1h protocol; got timeframe {ctx.primary.timeframe!r}"
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
                "BIC requires a contiguous native 1h series; "
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

        if self._phase == "flat" and self._may_signal(index, ctx.decision_time):
            side = self._signal(ctx)
            if side != 0.0:
                self._phase = "pending_entry"
                self._side = side
                self._planned_entry_ts = ctx.decision_time
                self._accepted_events += 1
                if side > 0:
                    self._long_events += 1
                else:
                    self._short_events += 1

        self._prev_ts = bar.ts
        target = (
            self._side * self.config.target_weight
            if self._phase in ("pending_entry", "holding")
            else 0.0
        )
        return Intent(target=target, reason=self.name)

    # ---- state transitions --------------------------------------------

    def _resolve_entry(self, index: int, volume: float) -> None:
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
            raise RuntimeError("voided BIC entry has no planned timestamp")
        self._phase = "flat"
        self._side = 0.0
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
        self._side = 0.0
        self._entry_index = None

    # ---- signal -------------------------------------------------------

    def _may_signal(self, index: int, planned_entry_ts: int) -> bool:
        if index < self.config.baseline_bars + 1:
            return False
        cooldown = self._cooldown_start_ts
        return (
            cooldown is None
            or planned_entry_ts - cooldown >= self.config.cooldown_bars * BAR_MS
        )

    def _signal(self, ctx: Context) -> float:
        """Direction of the impulse, or 0.0 when this bar is not one.

        The trailing baseline is taken over returns strictly before the signal
        bar: the current bar can never enter the window that judges it.
        """
        c = self.config
        window = c.baseline_bars + 2

        ts = ctx.primary.timestamps(window)
        if not bool(np.all(np.diff(ts) == BAR_MS)):
            return 0.0

        closes = ctx.close(window)
        volumes = ctx.volume(window)
        if not bool(np.all(np.isfinite(closes))) or not bool(np.all(closes > 0.0)):
            return 0.0
        if float(volumes[-1]) <= 0.0:
            return 0.0

        returns = np.diff(np.log(closes))  # length baseline_bars + 1
        baseline = np.abs(returns[:-1])  # strictly before the signal bar
        signal_return = float(returns[-1])
        threshold = float(np.quantile(baseline, c.quantile))
        if not np.isfinite(threshold) or threshold <= 0.0:
            return 0.0
        if abs(signal_return) <= threshold:
            return 0.0
        return 1.0 if signal_return > 0.0 else -1.0
