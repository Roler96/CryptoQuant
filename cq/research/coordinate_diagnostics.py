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

# Three primary measures, family alpha 0.05.
SIDAK_ALPHA = 1.0 - 0.95 ** (1.0 / 3.0)


@dataclass(frozen=True)
class HitRate:
    """Directional agreement between consecutive returns."""

    rate: float
    pairs: int
    dropped: int


@dataclass(frozen=True)
class Combined:
    """One measure's evidence, pooled across scales."""

    statistic: float
    p_value: float
    sign_agreement: int


@dataclass(frozen=True)
class GateReport:
    """The pre-registered verdict."""

    g1_passed: bool
    g2_passed: bool
    g3_passed: bool
    winning_measure: str | None
    verdict: str  # PASS | CLOSED | INVALID


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

    Sanity check only, not a finding. The gate compares kurtosis of the same
    data under two aggregation schemes: calendar time versus dollar time. Under
    stochastic volatility with trading activity correlated to volatility (the
    standard market microstructure assumption), calendar aggregation can
    increase kurtosis; dollar-time aggregation adapts to activity intensity and
    absorbs the heteroskedasticity. A dollar clock implementation is suspect if
    its kurtosis exceeds calendar kurtosis, which would violate the subordination
    property rather than refute the clock effect.
    """
    r = np.asarray(returns, dtype=np.float64)
    r = r[np.isfinite(r)]
    if r.size < 4:
        return float("nan")
    return float(stats.kurtosis(r, fisher=True, bias=False))


def stationary_bootstrap_indices(
    n: int,
    mean_block: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Politis-Romano stationary bootstrap: geometric blocks, wrapping at the end.

    Blocks are what keep the null honest. Resampling observation by observation
    would destroy the series' own short-range dependence along with the coupling
    under test, and the resulting null would be far too easy to beat.
    """
    if n < 1:
        raise ValueError("n must be at least 1")
    if mean_block <= 0.0:
        raise ValueError("mean_block must be positive")

    restart_probability = 1.0 / mean_block
    indices = np.empty(n, dtype=np.int64)
    current = int(rng.integers(n))
    restarts = rng.random(n) < restart_probability
    for position in range(n):
        if position > 0:
            current = int(rng.integers(n)) if restarts[position] else (current + 1) % n
        indices[position] = current
    return indices


def select_block_length(returns: np.ndarray, max_lag: int = 288) -> int:
    """First lag whose |ACF| falls inside the +-2/sqrt(n) band, rounded up to an hour.

    Pre-registered as a rule rather than a number so it cannot be retuned after
    seeing the result. The 12-bar rounding is one hour of 5m bars.
    """
    r = np.asarray(returns, dtype=np.float64)
    r = r[np.isfinite(r)]
    n = r.size
    if n < 100:
        return 12
    centred = r - r.mean()
    denominator = float(np.dot(centred, centred))
    if denominator == 0.0:
        return 12
    band = 2.0 / np.sqrt(n)
    chosen = max_lag
    for lag in range(1, min(max_lag, n - 1) + 1):
        acf = float(np.dot(centred[:-lag], centred[lag:]) / denominator)
        if abs(acf) < band:
            chosen = lag
            break
    return max(12, int(np.ceil(chosen / 12.0)) * 12)


def combine_scales(observed: np.ndarray, null_draws: np.ndarray) -> Combined:
    """Pool paired differences across scales against a jointly generated null.

    Each scale is normalised by its own null spread, then summed. Because the
    null draws are generated jointly, the correlation between scales is already
    inside the null distribution of the sum — no independence assumption is made
    anywhere.
    """
    delta = np.asarray(observed, dtype=np.float64)
    draws = np.asarray(null_draws, dtype=np.float64)
    if draws.ndim != 2 or draws.shape[1] != delta.size:
        raise ValueError("null_draws must have shape (B, n_scales)")

    # observed must be fully finite.
    if not np.all(np.isfinite(delta)):
        non_finite_indices = np.where(~np.isfinite(delta))[0]
        raise ValueError(
            f"observed contains non-finite values at scales {non_finite_indices.tolist()}"
        )

    spread = draws.std(axis=0, ddof=1)

    # The null distribution's spread must all be strictly positive.
    if not np.all(spread > 0):
        zero_var_indices = np.where(spread <= 0)[0]
        raise ValueError(
            f"null distribution has zero or negative variance at scales {zero_var_indices.tolist()}"
        )

    statistic = float(np.sum(delta / spread))
    null_statistics = np.sum(draws / spread, axis=1)

    # Two-sided, with the +1 that keeps an empirical p-value from ever being 0.
    extreme = int(np.sum(np.abs(null_statistics) >= abs(statistic)))
    p_value = (extreme + 1) / (draws.shape[0] + 1)

    positive = int(np.sum(delta > 0))
    negative = int(np.sum(delta < 0))
    return Combined(
        statistic=statistic,
        p_value=float(p_value),
        sign_agreement=max(positive, negative),
    )


def evaluate_gates(
    combined: dict[str, float],
    sign_agreement: dict[str, int],
    kurtosis_reduced_scales: int,
    n_scales: int,
) -> GateReport:
    """Apply G1/G2/G3 exactly as pre-registered in the protocol.

    G2 is deliberately not a research verdict. Aggregating by traded value is
    known to reduce kurtosis; if it did not, the clock is mis-built and the run
    says INVALID rather than pretending to have measured the market.

    When multiple measures share the winning p-value, the measure earliest in
    alphabetical order is chosen as the winner.
    """
    required = int(np.ceil(0.75 * n_scales))

    g2_passed = kurtosis_reduced_scales >= required

    significant = {name: p for name, p in combined.items() if p <= SIDAK_ALPHA}
    g1_passed = bool(significant)

    winner = min(significant, key=lambda name: (combined[name], name)) if significant else None
    g3_passed = bool(winner is not None and sign_agreement[winner] >= required)

    if not g2_passed:
        verdict = "INVALID"
    elif g1_passed and g3_passed:
        verdict = "PASS"
    else:
        verdict = "CLOSED"

    return GateReport(
        g1_passed=g1_passed,
        g2_passed=g2_passed,
        g3_passed=g3_passed,
        winning_measure=winner,
        verdict=verdict,
    )


def _aggregate_returns(returns: np.ndarray, ends: np.ndarray) -> np.ndarray:
    """Sum 5m log returns inside each bucket. Additivity is why they are logs.

    `ends` comes from `bucket_edges` run against the turnover series, which can
    be one bar longer than the return series -- a return needs a price and its
    predecessor, so n+1 bars of turnover yield only n returns. Any edge landing
    past the end of `returns` is therefore an artifact of that extra bar, not a
    real bucket boundary in return-space, and is dropped exactly the way
    `bucket_edges` itself drops a trailing partial bucket.
    """
    if ends.size == 0:
        return np.empty(0, dtype=np.float64)
    usable_ends = ends[ends <= returns.size]
    if usable_ends.size == 0:
        return np.empty(0, dtype=np.float64)
    starts = np.concatenate(([0], usable_ends[:-1]))
    return np.add.reduceat(returns, starts)


def _measure(name: str, aggregated: np.ndarray) -> float:
    if name == "rank_autocorrelation":
        return rank_autocorrelation(aggregated, lag=1)
    if name == "hit_rate":
        return direction_hit_rate(aggregated).rate
    raise ValueError(f"unknown measure {name!r}")


def paired_null_draws(
    returns_5m: np.ndarray,
    quote_volume: np.ndarray,
    edges_by_scale: dict[int, np.ndarray],
    calendar_factors: list[int],
    measure: str,
    draws: int,
    mean_block: float,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Observed paired differences and their null distribution.

    The null resamples the 5m return series in stationary blocks while leaving
    turnover untouched. Both clocks therefore keep exactly the partition they
    had; the only thing broken is the coupling between when returns happened and
    how much traded. That is precisely the hypothesis "the clock change bought
    nothing", and nothing else about the data is disturbed.

    Because turnover is frozen, `edges_by_scale` is computed once by the caller
    and reused across every draw.
    """
    returns = np.asarray(returns_5m, dtype=np.float64)
    n = returns.size
    rng = np.random.default_rng(seed)

    def deltas(series: np.ndarray) -> np.ndarray:
        out = []
        for factor in calendar_factors:
            usable = (n // factor) * factor
            calendar_ends = np.arange(factor, usable + 1, factor, dtype=np.int64)
            dollar = _measure(measure, _aggregate_returns(series, edges_by_scale[factor]))
            calendar = _measure(measure, _aggregate_returns(series[:usable], calendar_ends))
            out.append(dollar - calendar)
        return np.asarray(out, dtype=np.float64)

    observed = deltas(returns)
    null = np.empty((draws, len(calendar_factors)), dtype=np.float64)
    for draw in range(draws):
        indices = stationary_bootstrap_indices(n, mean_block, rng)
        null[draw] = deltas(returns[indices])
    return observed, null


def delta_paired_null_draws(
    dollar_delta: dict[int, np.ndarray],
    dollar_forward: dict[int, np.ndarray],
    calendar_delta: dict[int, np.ndarray],
    calendar_forward: dict[int, np.ndarray],
    factors: list[int],
    draws: int,
    mean_block: float,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Observed and null paired differences for delta's predictive power.

    The second null of the protocol: only the delta series is reshuffled, in
    stationary blocks. Returns and turnover are left exactly as they were, so
    both clocks keep their partitions and their price paths — the single thing
    broken is the coupling between the volume centroid and what happens next.

    Shuffling the whole bar instead would move `close` (returns change) and
    `quote_volume` (the buckets no longer match the data), and an i.i.d. shuffle
    would strip the local dependence the block bootstrap exists to preserve —
    narrowing the null and manufacturing significance.
    """
    rng = np.random.default_rng(seed)

    def paired(shuffled: bool) -> np.ndarray:
        out = []
        for factor in factors:
            values = []
            for feature, forward in (
                (dollar_delta[factor], dollar_forward[factor]),
                (calendar_delta[factor], calendar_forward[factor]),
            ):
                series = feature
                if shuffled:
                    series = feature[stationary_bootstrap_indices(feature.size, mean_block, rng)]
                values.append(abs(rank_predictive_power(series, forward)))
            out.append(values[0] - values[1])
        return np.asarray(out, dtype=np.float64)

    observed = paired(shuffled=False)
    null = np.empty((draws, len(factors)), dtype=np.float64)
    for draw in range(draws):
        null[draw] = paired(shuffled=True)
    return observed, null
