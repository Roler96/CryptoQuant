"""Funding models for perpetual swaps.

OKX only serves about three months of funding history, so a swap backtest
over five years cannot use measured rates for most of its span. Rather than
pretend the missing rates are zero, the mode is an explicit choice that
travels with the result:

* `off` — funding ignored. The result is **not an estimate**: it omits a cost
  that is usually, but not always, a drag. A long pays when the rate is
  positive and a short pays when it is negative, so for those the omission
  flatters the result — but a short holding through positive funding, or a
  long through negative funding, is *receiving* it, and ignoring that
  understates the run instead. "Upper bound" was the old wording here and it
  was simply wrong in those two cases. Every prior study in this project was
  computed this way, so it is also the mode that makes those numbers
  comparable.
* `actual` — measured rates from the archive. Raises on any gap, because a
  silently skipped settlement is indistinguishable from a free hold.
* `assumed` — a constant rate, for sensitivity analysis. Labelled as an
  assumption wherever it is reported, never as a measurement.
"""

from __future__ import annotations

import bisect
import hashlib
import itertools
from dataclasses import dataclass
from typing import Protocol

from cq.core.clock import HOUR_MS
from cq.data.store import Store

# OKX settles funding at 00:00, 08:00 and 16:00 UTC.
SETTLEMENT_INTERVAL_MS = 8 * HOUR_MS


class MissingFundingError(LookupError):
    """A settlement fell inside the tested range but is not in the archive."""


class FundingModel(Protocol):
    """Yields the settlements that occur within a half-open interval."""

    @property
    def label(self) -> str: ...

    @property
    def fingerprint(self) -> str:
        """Identifies the rates used, so a report can be reproduced."""
        ...

    def settlements(self, start_ms: int, end_ms: int) -> list[tuple[int, float]]: ...


@dataclass(frozen=True)
class NoFunding:
    """Funding ignored: a cost omitted, in whichever direction it ran."""

    @property
    def label(self) -> str:
        return (
            "off (funding omitted entirely; flattering while the position paid "
            "it and understating while the position received it)"
        )

    @property
    def fingerprint(self) -> str:
        return "off"

    def settlements(self, start_ms: int, end_ms: int) -> list[tuple[int, float]]:
        return []


@dataclass(frozen=True)
class AssumedFunding:
    """A constant rate per settlement, for sensitivity analysis."""

    rate: float

    @property
    def label(self) -> str:
        return f"assumed {self.rate * 10_000:.2f} bps/settlement (an assumption, not a measurement)"

    @property
    def fingerprint(self) -> str:
        return f"assumed:{self.rate!r}"

    def settlements(self, start_ms: int, end_ms: int) -> list[tuple[int, float]]:
        return [(ts, self.rate) for ts in settlement_times(start_ms, end_ms)]


class ActualFunding:
    """Measured rates. Any missing settlement is an error, never a zero.

    The settlement cadence is read from the archive rather than assumed. OKX
    settles most swaps every eight hours but does not promise to: it has run
    four-hour and one-hour schedules on individual instruments, and a model
    that walks a hard-coded eight-hour grid over a four-hour instrument silently
    charges a third of the funding that was actually paid.
    """

    def __init__(self, rates: dict[int, float], inst_id: str = "", interval_ms: int = 0):
        self._rates = dict(rates)
        self._times = sorted(self._rates)
        self._inst_id = inst_id
        self._interval = interval_ms or _infer_interval(self._times)

    @property
    def label(self) -> str:
        hours = self._interval / HOUR_MS
        return f"actual ({len(self._rates)} archived settlements, {hours:g}h cadence)"

    @property
    def interval_ms(self) -> int:
        """The settlement cadence observed in the archive."""
        return self._interval

    @property
    def covered_range(self) -> tuple[int, int] | None:
        if not self._times:
            return None
        return (self._times[0], self._times[-1])

    @property
    def fingerprint(self) -> str:
        """Hash of the rates a run actually consumed."""
        digest = hashlib.sha256(self._inst_id.encode())
        for ts in self._times:
            digest.update(f"{ts}:{self._rates[ts]!r}".encode())
        return f"actual:{digest.hexdigest()[:16]}"

    def settlements(self, start_ms: int, end_ms: int) -> list[tuple[int, float]]:
        if end_ms <= start_ms:
            return []
        lo = bisect.bisect_left(self._times, start_ms)
        hi = bisect.bisect_left(self._times, end_ms)
        found = self._times[lo:hi]
        self._require_full_coverage(start_ms, end_ms, len(found))
        return [(ts, self._rates[ts]) for ts in found]

    def _require_full_coverage(self, start_ms: int, end_ms: int, found: int) -> None:
        """Fail unless every settlement in the window is archived."""
        if not self._times:
            raise MissingFundingError(self._explain(start_ms, end_ms, "the archive is empty"))

        first, last = self._times[0], self._times[-1]
        # The archive can only speak for the span it covers: the last stored
        # settlement pays for the period that follows it, and nothing before
        # the first one is knowable at all.
        if start_ms < first or end_ms > last + self._interval:
            covered = f"{first}..{last + self._interval}"
            raise MissingFundingError(
                self._explain(start_ms, end_ms, f"the archive only covers {covered}")
            )

        expected = _grid_count(first, self._interval, start_ms, end_ms)
        if found != expected:
            raise MissingFundingError(
                self._explain(
                    start_ms,
                    end_ms,
                    f"expected {expected} settlements at a {self._interval / HOUR_MS:g}h "
                    f"cadence but the archive holds {found}",
                )
            )

    def _explain(self, start_ms: int, end_ms: int, because: str) -> str:
        return (
            f"{self._inst_id or 'instrument'}: no archived funding rate for every "
            f"settlement in [{start_ms}, {end_ms}) — {because}. Treating the gap as "
            f"zero would report a hold as free. Use funding=off (which omits funding "
            f"entirely and says so) or restrict the range to the archived window."
        )


def _infer_interval(times: list[int]) -> int:
    """Settlement cadence implied by the archived timestamps.

    The shortest observed gap, so an instrument that settles more often than
    every eight hours is charged for every settlement it actually had.
    """
    if len(times) < 2:
        return SETTLEMENT_INTERVAL_MS
    gaps = [later - earlier for earlier, later in itertools.pairwise(times) if later > earlier]
    return min(gaps) if gaps else SETTLEMENT_INTERVAL_MS


def _grid_count(anchor: int, interval: int, start_ms: int, end_ms: int) -> int:
    """How many `interval`-spaced instants from `anchor` fall in [start, end)."""
    first = anchor + -(-(start_ms - anchor) // interval) * interval
    if first >= end_ms:
        return 0
    return (end_ms - first - 1) // interval + 1


def settlement_times(start_ms: int, end_ms: int) -> list[int]:
    """Settlement instants in [start_ms, end_ms).

    Anchored to the epoch, which lands on 00:00/08:00/16:00 UTC — the grid OKX
    uses for most swaps. This is the *assumed* grid: measured funding reads its
    cadence from the archive instead, in `ActualFunding`.
    """
    if end_ms <= start_ms:
        return []
    first = -(-start_ms // SETTLEMENT_INTERVAL_MS) * SETTLEMENT_INTERVAL_MS
    return list(range(first, end_ms, SETTLEMENT_INTERVAL_MS))


def load_actual_funding(store: Store, inst_id: str) -> ActualFunding:
    """Build a measured-funding model from the archive."""
    return ActualFunding(store.load_funding(inst_id), inst_id=inst_id)
