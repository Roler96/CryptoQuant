"""Sampling the tape by traded value instead of by the wall clock.

Over the explore window a 5m bar carries anywhere from 2,163 to 131,612,597
USDT of turnover -- the p99/p50 ratio alone is 47x. Feeding both into the same
rule as one observation is what a calendar clock does, and an effect that is
stable in event time gets phase-randomised and averaged away by it. Rebucketing
by equal traded value removes that distortion; what it cannot remove is the 5m
sampling floor, so bucket boundaries land only on 5m edges and every bucket
slightly overshoots its target. That overshoot is measured and reported, never
hidden.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BucketSolution:
    """The bucket size that makes the dollar clock match a calendar sample count."""

    target_value: float
    count: int
    iterations: int
    converged: bool


def bucket_edges(quote_volume: np.ndarray, target: float) -> np.ndarray:
    """Right-exclusive end index of each equal-dollar bucket.

    A bucket closes on the first 5m bar whose cumulative turnover reaches
    `target`; the overshoot is *not* carried forward, so each bucket is the
    shortest run of bars whose turnover is at least `target`. A trailing run
    that never reaches the target is discarded rather than emitted short.
    """
    if target <= 0.0:
        raise ValueError("target must be positive")
    qv = np.asarray(quote_volume, dtype=np.float64)
    edges: list[int] = []
    accumulated = 0.0
    for index in range(qv.size):
        accumulated += qv[index]
        if accumulated >= target:
            edges.append(index + 1)
            accumulated = 0.0
    return np.asarray(edges, dtype=np.int64)


def solve_bucket_size(
    quote_volume: np.ndarray,
    target_count: int,
    max_iter: int = 100,
) -> BucketSolution:
    """Bisect the bucket size until the dollar clock emits `target_count` buckets.

    Sample-size matching is what makes the paired comparison fair: both clocks
    must span the same window with the same number of observations, so the only
    remaining difference is where the boundaries fall. Taking the naive
    `total / N` undershoots, because every bucket overshoots its target.

    Bucket count is non-increasing in bucket size, which is what makes the
    bisection valid.
    """
    if target_count < 1:
        raise ValueError("target_count must be at least 1")
    qv = np.asarray(quote_volume, dtype=np.float64)
    total = float(qv.sum())
    if total <= 0.0:
        raise ValueError("quote_volume must contain positive turnover")

    tolerance = max(1, int(0.001 * target_count))

    # Provable bracket, not a magic factor. Bucket count is maximised when the
    # bucket size is smallest, and any target at or below the smallest non-zero
    # turnover makes every non-empty bar its own bucket -- that is the ceiling.
    # A heuristic lower bound can start above the true solution, in which case
    # the branch that would widen the search never fires and a perfectly
    # matchable target is reported unconverged. Heavy-tailed turnover (this
    # module's whole subject) is exactly where that happens.
    low = float(qv[qv > 0].min())
    high = total
    reachable = len(bucket_edges(qv, low))
    if reachable < target_count:
        return BucketSolution(
            target_value=low,
            count=reachable,
            iterations=0,
            converged=abs(reachable - target_count) <= tolerance,
        )

    best = (low, reachable)
    used = 0

    for _ in range(1, max_iter + 1):
        used += 1
        mid = 0.5 * (low + high)
        if mid in (low, high):
            break
        count = len(bucket_edges(qv, mid))
        if abs(count - target_count) < abs(best[1] - target_count):
            best = (mid, count)
        if count == target_count:
            best = (mid, count)
            break
        if count > target_count:
            low = mid  # too many buckets: they are too small
        else:
            high = mid

    return BucketSolution(
        target_value=best[0],
        count=best[1],
        iterations=used,
        converged=abs(best[1] - target_count) <= tolerance,
    )


BAR_MS = 300_000

_COLUMNS = [
    "open",
    "high",
    "low",
    "close",
    "volume",
    "quote_volume",
    "duration_ms",
    "bars",
]


def aggregate_by_edges(frame: pd.DataFrame, edges: np.ndarray) -> pd.DataFrame:
    """Collapse 5m bars into the buckets delimited by `edges`.

    `duration_ms` is the calendar time the bucket consumed. Once turnover per
    bucket is held constant, that duration is where the information about
    activity went — and it is a variable no prior study in this repository has
    carried.

    `edges` must be strictly increasing with a first element >= 1: they are
    right-exclusive end indices consumed by `np.add.reduceat`, and reduceat
    does not validate monotonicity. Given a non-increasing index it silently
    returns `a[i]` instead of a sum for the offending segment, so a malformed
    `edges` array would otherwise produce wrong-but-plausible bars (and
    negative `bars`/`duration_ms`) instead of raising.
    """
    ends = np.asarray(edges, dtype=np.int64)
    if ends.size == 0:
        return pd.DataFrame(columns=_COLUMNS, index=frame.index[:0])

    if ends[0] < 1:
        raise ValueError(f"edges[0] must be >= 1, got {int(ends[0])}")
    non_increasing = np.where(np.diff(ends) <= 0)[0]
    if non_increasing.size > 0:
        first = int(non_increasing[0])
        raise ValueError(
            f"edges must be strictly increasing: edges[{first}]={int(ends[first])} "
            f">= edges[{first + 1}]={int(ends[first + 1])}"
        )

    starts = np.concatenate(([0], ends[:-1]))

    # reduceat's final segment always runs to the end of the array, but
    # `bucket_edges` discards the trailing partial bucket, so `ends[-1]` is
    # normally short of the frame. Without this truncation the last bucket
    # silently swallows the bars that were deliberately dropped.
    stop = int(ends[-1])

    def column(name: str) -> np.ndarray:
        return frame[name].to_numpy()[:stop]

    rows = {
        "open": column("open")[starts],
        "high": np.maximum.reduceat(column("high"), starts),
        "low": np.minimum.reduceat(column("low"), starts),
        "close": column("close")[ends - 1],
        "volume": np.add.reduceat(column("volume"), starts),
        "quote_volume": np.add.reduceat(column("quote_volume"), starts),
        "duration_ms": (ends - starts) * BAR_MS,
        "bars": ends - starts,
    }
    return pd.DataFrame(rows, index=frame.index[starts])


def aggregate_calendar(frame: pd.DataFrame, factor: int) -> pd.DataFrame:
    """Collapse 5m bars into fixed groups of `factor` — the calendar clock arm.

    Deliberately routed through the same aggregation as the dollar clock so the
    two arms of the paired comparison cannot differ by an accident of plumbing.
    """
    if factor < 1:
        raise ValueError("factor must be at least 1")
    usable = (len(frame) // factor) * factor
    edges = np.arange(factor, usable + 1, factor, dtype=np.int64)
    return aggregate_by_edges(frame.iloc[:usable], edges)
