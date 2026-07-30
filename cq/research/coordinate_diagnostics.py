"""Measuring whether a clock change buys predictability.

The main criteria here are rank-based on purpose. DOGE's right tail is wide
enough that second-moment statistics get dominated by a handful of bars, and
that is the technical root of this project's power wall: the effect was never
required to be absent, only the measurement was required to be blind to it.
Parametric measures are still computed, as corroboration — where the two
disagree, the disagreement is the finding.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats


@dataclass(frozen=True)
class HitRate:
    """Directional agreement between consecutive returns."""

    rate: float
    pairs: int
    dropped: int


def rank_autocorrelation(returns: np.ndarray, lag: int = 1) -> float:
    """Spearman correlation between a return and the return `lag` steps later."""
    if lag < 1:
        raise ValueError("lag must be at least 1")
    values = np.asarray(returns, dtype=np.float64)
    if values.size <= lag + 1:
        return float("nan")
    rho, _ = stats.spearmanr(values[:-lag], values[lag:])
    return float(rho)


def direction_hit_rate(returns: np.ndarray) -> HitRate:
    """How often the next return keeps the current one's sign.

    Flat bars carry no direction, so pairs touching a zero return are dropped
    rather than silently counted as agreement or disagreement.
    """
    signs = np.sign(np.asarray(returns, dtype=np.float64))
    current, following = signs[:-1], signs[1:]
    usable = (current != 0) & (following != 0)
    pairs = int(usable.sum())
    dropped = int(usable.size - pairs)
    if pairs == 0:
        return HitRate(rate=float("nan"), pairs=0, dropped=dropped)
    hits = float((current[usable] == following[usable]).sum())
    return HitRate(rate=hits / pairs, pairs=pairs, dropped=dropped)


def rank_predictive_power(feature: np.ndarray, forward_returns: np.ndarray) -> float:
    """Spearman correlation between a feature and the return that follows it."""
    x = np.asarray(feature, dtype=np.float64)
    y = np.asarray(forward_returns, dtype=np.float64)
    if x.size != y.size:
        raise ValueError("feature and forward_returns must have the same length")
    if x.size < 3:
        return float("nan")
    rho, _ = stats.spearmanr(x, y)
    return float(rho)
