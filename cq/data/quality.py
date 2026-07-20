"""Data quality checks.

Nothing here repairs anything. A gap that gets silently forward-filled turns
into a bar the market never printed, and every downstream statistic then
describes a market that did not exist. Problems are reported with exact
locations so the caller decides what to do.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

import pandas as pd

from cq.core.clock import duration_ms


@dataclass(frozen=True)
class Gap:
    """A run of bars the exchange never gave us."""

    start: pd.Timestamp
    end: pd.Timestamp
    missing: int

    def __str__(self) -> str:
        return f"{self.start:%Y-%m-%d %H:%M} .. {self.end:%Y-%m-%d %H:%M} ({self.missing} bars)"


@dataclass
class QualityReport:
    """What is wrong with one instrument's stored series."""

    inst_id: str
    timeframe: str
    bars: int
    first: pd.Timestamp | None = None
    last: pd.Timestamp | None = None
    gaps: list[Gap] = field(default_factory=list)
    duplicate_timestamps: list[pd.Timestamp] = field(default_factory=list)
    out_of_order: int = 0
    zero_volume_bars: list[pd.Timestamp] = field(default_factory=list)
    non_positive_prices: list[pd.Timestamp] = field(default_factory=list)
    inconsistent_ohlc: list[pd.Timestamp] = field(default_factory=list)

    @property
    def missing_bars(self) -> int:
        return sum(gap.missing for gap in self.gaps)

    @property
    def clean(self) -> bool:
        return not (
            self.gaps
            or self.duplicate_timestamps
            or self.out_of_order
            or self.non_positive_prices
            or self.inconsistent_ohlc
        )

    def summary(self) -> str:
        if not self.bars:
            return f"{self.inst_id} {self.timeframe}: no data"
        parts = [f"{self.bars} bars"]
        if self.gaps:
            parts.append(f"{len(self.gaps)} gaps / {self.missing_bars} missing")
        if self.duplicate_timestamps:
            parts.append(f"{len(self.duplicate_timestamps)} duplicate ts")
        if self.out_of_order:
            parts.append(f"{self.out_of_order} out of order")
        if self.non_positive_prices:
            parts.append(f"{len(self.non_positive_prices)} non-positive prices")
        if self.inconsistent_ohlc:
            parts.append(f"{len(self.inconsistent_ohlc)} inconsistent OHLC")
        if self.zero_volume_bars:
            parts.append(f"{len(self.zero_volume_bars)} zero volume")
        return f"{self.inst_id} {self.timeframe}: " + ", ".join(parts)


def check_ohlcv(frame: pd.DataFrame, inst_id: str, timeframe: str) -> QualityReport:
    """Inspect a stored OHLCV frame indexed by UTC open time."""
    report = QualityReport(inst_id=inst_id, timeframe=timeframe, bars=len(frame))
    if frame.empty:
        return report

    index = pd.DatetimeIndex(frame.index)
    report.first = cast(pd.Timestamp, index[0])
    report.last = cast(pd.Timestamp, index[-1])

    duplicated = index[index.duplicated()]
    report.duplicate_timestamps = list(pd.unique(duplicated))

    # Storage returns sorted rows, so disorder here means the data arrived
    # that way — worth surfacing rather than quietly sorting.
    deltas = index.to_series().diff()
    report.out_of_order = int((deltas < pd.Timedelta(0)).sum())

    report.gaps = find_gaps(index, timeframe)

    closes = frame["close"]
    opens = frame["open"]
    highs = frame["high"]
    lows = frame["low"]

    non_positive = frame[(opens <= 0) | (highs <= 0) | (lows <= 0) | (closes <= 0)]
    report.non_positive_prices = list(non_positive.index)

    # high must bound every other price, low must floor them.
    #
    # `highs < lows` is subsumed by the four bounds that follow: if high < low
    # then open cannot sit in the empty interval between them, so either
    # `highs < opens` or `lows > opens` already fires. It is kept because it
    # states the intended invariant directly — but it can never be the only
    # clause that catches a bar, so no test can isolate it.
    bad = frame[
        (highs < lows)
        | (highs < opens)
        | (highs < closes)
        | (lows > opens)
        | (lows > closes)
    ]
    report.inconsistent_ohlc = list(bad.index)

    # Zero volume is legal on illiquid instruments, so it is reported but does
    # not by itself make a series unclean.
    report.zero_volume_bars = list(frame[frame["volume"] <= 0].index)

    return report


def find_gaps(index: pd.DatetimeIndex, timeframe: str) -> list[Gap]:
    """Runs of absent bars in an ascending, evenly spaced index."""
    if len(index) < 2:
        return []
    step = pd.Timedelta(milliseconds=duration_ms(timeframe))
    deltas = index.to_series().diff()

    gaps: list[Gap] = []
    for position, delta in enumerate(deltas):
        if position == 0 or pd.isna(delta) or delta <= step:
            continue
        missing = int(delta / step) - 1
        gaps.append(
            Gap(
                start=index[position - 1] + step,
                end=index[position] - step,
                missing=missing,
            )
        )
    return gaps
