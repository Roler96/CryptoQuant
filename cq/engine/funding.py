"""Funding models for perpetual swaps.

OKX only serves about three months of funding history, so a swap backtest
over five years cannot use measured rates for most of its span. Rather than
pretend the missing rates are zero, the mode is an explicit choice that
travels with the result:

* `off` — funding ignored. The result is an **upper bound**, not an estimate.
  Every prior study in this project was computed this way, so it is also the
  mode that makes those numbers comparable.
* `actual` — measured rates from the archive. Raises on any gap, because a
  silently skipped settlement is indistinguishable from a free hold.
* `assumed` — a constant rate, for sensitivity analysis. Labelled as an
  assumption wherever it is reported, never as a measurement.
"""

from __future__ import annotations

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

    def settlements(self, start_ms: int, end_ms: int) -> list[tuple[int, float]]: ...


@dataclass(frozen=True)
class NoFunding:
    """Funding ignored. Results are an upper bound."""

    @property
    def label(self) -> str:
        return "off (results are an upper bound)"

    def settlements(self, start_ms: int, end_ms: int) -> list[tuple[int, float]]:
        return []


@dataclass(frozen=True)
class AssumedFunding:
    """A constant rate per settlement, for sensitivity analysis."""

    rate: float

    @property
    def label(self) -> str:
        return f"assumed {self.rate * 10_000:.2f} bps/settlement (an assumption, not a measurement)"

    def settlements(self, start_ms: int, end_ms: int) -> list[tuple[int, float]]:
        return [(ts, self.rate) for ts in settlement_times(start_ms, end_ms)]


class ActualFunding:
    """Measured rates. Any missing settlement is an error, never a zero."""

    def __init__(self, rates: dict[int, float], inst_id: str = ""):
        self._rates = dict(rates)
        self._inst_id = inst_id

    @property
    def label(self) -> str:
        return f"actual ({len(self._rates)} archived settlements)"

    @property
    def covered_range(self) -> tuple[int, int] | None:
        if not self._rates:
            return None
        return (min(self._rates), max(self._rates))

    def settlements(self, start_ms: int, end_ms: int) -> list[tuple[int, float]]:
        out: list[tuple[int, float]] = []
        for ts in settlement_times(start_ms, end_ms):
            if ts not in self._rates:
                raise MissingFundingError(
                    f"{self._inst_id or 'instrument'}: no archived funding rate for "
                    f"settlement at {ts}; treating it as zero would understate the "
                    f"cost of holding. Use funding=off (an upper bound) or restrict "
                    f"the range to the archived window."
                )
            out.append((ts, self._rates[ts]))
        return out


def settlement_times(start_ms: int, end_ms: int) -> list[int]:
    """Settlement instants in [start_ms, end_ms).

    Anchored to the epoch, which lands on 00:00/08:00/16:00 UTC — the same
    grid OKX uses.
    """
    if end_ms <= start_ms:
        return []
    first = -(-start_ms // SETTLEMENT_INTERVAL_MS) * SETTLEMENT_INTERVAL_MS
    return list(range(first, end_ms, SETTLEMENT_INTERVAL_MS))


def load_actual_funding(store: Store, inst_id: str) -> ActualFunding:
    """Build a measured-funding model from the archive."""
    return ActualFunding(store.load_funding(inst_id), inst_id=inst_id)
