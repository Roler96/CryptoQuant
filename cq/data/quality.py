"""Data quality checks.

Nothing here repairs anything. A gap that gets silently forward-filled turns
into a bar the market never printed, and every downstream statistic then
describes a market that did not exist. Problems are reported with exact
locations so the caller decides what to do.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

import numpy as np
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
    # A warning, not a fault: an illiquid bar can legitimately trade nothing.
    zero_volume_bars: list[pd.Timestamp] = field(default_factory=list)
    # Hard faults. A negative volume, a non-finite price, or a timestamp off the
    # timeframe grid is not a quiet oddity — it is a value the exchange cannot
    # have printed, and trading on it means trading on corruption.
    negative_volume_bars: list[pd.Timestamp] = field(default_factory=list)
    non_finite_values: list[pd.Timestamp] = field(default_factory=list)
    misaligned_timestamps: list[pd.Timestamp] = field(default_factory=list)
    non_positive_prices: list[pd.Timestamp] = field(default_factory=list)
    inconsistent_ohlc: list[pd.Timestamp] = field(default_factory=list)

    @property
    def missing_bars(self) -> int:
        return sum(gap.missing for gap in self.gaps)

    @property
    def clean(self) -> bool:
        """Whether the series is fit to trade on.

        An empty series is not clean. "No data" is the most complete failure
        a series can have, and reporting it as clean means an unsynced
        database, a typo in an instrument id, and a healthy archive all exit
        zero — the check passes precisely when it has checked nothing.

        Zero volume is the one anomaly that does not fail this: it is common on
        thin instruments and the engine already refuses to fill against it. A
        *negative* volume is a different animal — it cannot occur, so it marks
        corruption — and it must fail here rather than hide among the zero-volume
        warnings, which is exactly what a single `volume <= 0` bucket let it do.
        """
        return bool(self.bars) and not (
            self.gaps
            or self.duplicate_timestamps
            or self.out_of_order
            or self.negative_volume_bars
            or self.non_finite_values
            or self.misaligned_timestamps
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
        if self.misaligned_timestamps:
            parts.append(f"{len(self.misaligned_timestamps)} off-grid ts")
        if self.non_finite_values:
            parts.append(f"{len(self.non_finite_values)} non-finite")
        if self.non_positive_prices:
            parts.append(f"{len(self.non_positive_prices)} non-positive prices")
        if self.inconsistent_ohlc:
            parts.append(f"{len(self.inconsistent_ohlc)} inconsistent OHLC")
        if self.negative_volume_bars:
            parts.append(f"{len(self.negative_volume_bars)} negative volume")
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

    # A bar's open time must land on the timeframe grid anchored to the epoch —
    # OKX's 4h bars sit at 00:00/04:00/... UTC, dailies at 00:00. An off-grid
    # timestamp means a mislabelled timeframe or a corrupted row, and every
    # spacing check downstream silently assumes the grid it violates.
    step_ms = duration_ms(timeframe)
    epoch_ms = index.asi8 // 1_000_000
    report.misaligned_timestamps = list(index[epoch_ms % step_ms != 0])

    report.gaps = find_gaps(index, timeframe)

    closes = frame["close"]
    opens = frame["open"]
    highs = frame["high"]
    lows = frame["low"]

    # NaN and ±inf survive every ordering comparison below as a silent False, so
    # they are caught first and on their own. quote_volume is nullable by design
    # and is not part of this check.
    price_volume = frame[["open", "high", "low", "close", "volume"]]
    non_finite = frame[~np.isfinite(price_volume).all(axis=1)]
    report.non_finite_values = list(non_finite.index)

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

    volume = frame["volume"]
    # A negative volume cannot happen; it is corruption and fails the series.
    # Zero volume is legal on illiquid instruments, so it is reported but does
    # not by itself make a series unclean. Splitting them keeps a genuine data
    # error from hiding inside a benign warning. NaN volume is neither of these
    # — it is caught above as non-finite — and the comparisons here skip it.
    report.negative_volume_bars = list(frame[volume < 0].index)
    report.zero_volume_bars = list(frame[volume == 0].index)

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
