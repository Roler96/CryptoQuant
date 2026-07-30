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
    low = total / (target_count * 50.0)
    high = total
    best = (low, len(bucket_edges(qv, low)))
    iterations = 0

    for _ in range(1, max_iter + 1):
        iterations += 1
        mid = 0.5 * (low + high)
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
        iterations=iterations,
        converged=abs(best[1] - target_count) <= tolerance,
    )
