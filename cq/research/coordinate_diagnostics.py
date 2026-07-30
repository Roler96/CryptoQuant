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
    rather than silently counted as agreement or disagreement. Missing values
    (NaN) are also dropped as they carry no direction information.
    """
    signs = np.sign(np.asarray(returns, dtype=np.float64))
    current, following = signs[:-1], signs[1:]
    usable = np.isfinite(current) & np.isfinite(following) & (current != 0) & (following != 0)
    pairs = int(usable.sum())
    dropped = int(usable.size - pairs)
    if pairs == 0:
        return HitRate(rate=float("nan"), pairs=0, dropped=dropped)
    hits = float((current[usable] == following[usable]).sum())
    return HitRate(rate=hits / pairs, pairs=pairs, dropped=dropped)


def rank_predictive_power(feature: np.ndarray, forward_returns: np.ndarray) -> float:
    """Spearman correlation between a feature and the return that follows it.

    The caller is responsible for time alignment: feature[t] must correspond to
    forward_returns[t], where feature[t] is observable at time t and
    forward_returns[t] is the return realized after time t. The function only
    validates that the arrays have equal length; it cannot detect semantic
    misalignment. If the caller mistakenly passes same-period returns instead
    of forward returns, the function will return a valid correlation that
    aliases autocorrelation as predictive power.
    """
    x = np.asarray(feature, dtype=np.float64)
    y = np.asarray(forward_returns, dtype=np.float64)
    if x.size != y.size:
        raise ValueError("feature and forward_returns must have the same length")
    if x.size < 3:
        return float("nan")
    rho, _ = stats.spearmanr(x, y)
    return float(rho)


def variance_ratio(returns: np.ndarray, q: int) -> float:
    """Lo-MacKinlay variance ratio; 1 under a random walk.

    Above 1 is trending, below 1 is reverting. Reported as corroboration only:
    it is a second-moment statistic and therefore exposed to the fat tail the
    rank measures are designed to survive.
    """
    if q < 2:
        raise ValueError("q must be at least 2")
    r = np.asarray(returns, dtype=np.float64)
    r = r[np.isfinite(r)]
    if r.size < 2 * q:
        return float("nan")
    single = float(np.var(r, ddof=1))
    if single == 0.0:
        return float("nan")
    aggregated = np.convolve(r, np.ones(q), mode="valid")
    return float(np.var(aggregated, ddof=1) / (q * single))


def delta_r_squared(feature: np.ndarray, forward_returns: np.ndarray) -> float:
    """R-squared of the univariate regression of forward return on the feature."""
    x = np.asarray(feature, dtype=np.float64)
    y = np.asarray(forward_returns, dtype=np.float64)
    if x.size != y.size:
        raise ValueError("feature and forward_returns must have the same length")
    usable = np.isfinite(x) & np.isfinite(y)
    if usable.sum() < 3:
        return float("nan")
    correlation = np.corrcoef(x[usable], y[usable])[0, 1]
    if not np.isfinite(correlation):
        return float("nan")
    return float(correlation**2)


def excess_kurtosis(returns: np.ndarray) -> float:
    """Excess kurtosis; zero for a normal.

    This is the sanity check, not a finding. Aggregating by traded value is
    known to pull return distributions toward normality, so a dollar clock that
    fails to reduce kurtosis indicates a broken clock, not an absent effect.
    """
    r = np.asarray(returns, dtype=np.float64)
    r = r[np.isfinite(r)]
    if r.size < 4:
        return float("nan")
    return float(stats.kurtosis(r, fisher=True, bias=False))
