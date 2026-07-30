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

import numpy as np


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
