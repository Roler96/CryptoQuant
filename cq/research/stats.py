"""Statistical adjudication.

A backtest number is a claim about one path drawn from a distribution that
was searched over. Three corrections are applied here, each because leaving
it out has already produced a wrong conclusion in this project:

* **Trade bootstrap** — the one surviving candidate had a ~10% probability of
  losing money over the full period, invisible in the headline return.
* **Family correction** — the audited spot router had p=0.0252 on its own and
  p≈0.40 once the twenty variants tried alongside it were counted.
* **Deflated Sharpe** — its PSR of 0.976 fell to 0.50 against the same
  twenty trials. A Sharpe is not evidence until it is deflated by how many
  were computed to find it.

Nothing here decides anything on its own. It exists to make the size of a
claim visible before it is believed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import stats

EULER_MASCHERONI = 0.5772156649015329


@dataclass(frozen=True)
class BootstrapResult:
    """Resampled distribution of a strategy's total result."""

    samples: int
    observed: float
    mean: float
    median: float
    probability_of_loss: float
    percentile_05: float
    percentile_95: float

    def summary(self) -> str:
        return (
            f"  bootstrap ({self.samples} resamples): median {self.median * 100:+.2f}%, "
            f"5-95% [{self.percentile_05 * 100:+.2f}%, {self.percentile_95 * 100:+.2f}%]\n"
            f"  probability of losing money: {self.probability_of_loss * 100:.1f}%"
        )


def bootstrap_trades(
    trade_returns: np.ndarray | list[float],
    samples: int = 10_000,
    seed: int = 0,
) -> BootstrapResult:
    """Resample trades with replacement and compound each draw.

    Answers "how much of this result was the order the trades happened to
    arrive in?" — a question a single equity curve cannot.
    """
    returns = np.asarray(trade_returns, dtype=np.float64)
    if len(returns) == 0:
        return BootstrapResult(samples, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    observed = float(np.prod(1.0 + returns) - 1.0)
    rng = np.random.default_rng(seed)
    draws = rng.choice(returns, size=(samples, len(returns)), replace=True)
    totals = np.prod(1.0 + draws, axis=1) - 1.0

    return BootstrapResult(
        samples=samples,
        observed=observed,
        mean=float(np.mean(totals)),
        median=float(np.median(totals)),
        probability_of_loss=float(np.mean(totals < 0)),
        percentile_05=float(np.percentile(totals, 5)),
        percentile_95=float(np.percentile(totals, 95)),
    )


def sidak_correction(p_value: float, trials: int) -> float:
    """Adjust a p-value for how many strategies were tried to find it.

    A result at p=0.03 found after twenty attempts is not a 3% surprise; it
    is roughly what twenty attempts produce by chance.
    """
    if trials < 1:
        raise ValueError("trials must be at least 1")
    if not 0.0 <= p_value <= 1.0:
        raise ValueError(f"p-value out of range: {p_value}")
    return 1.0 - (1.0 - p_value) ** trials


def probabilistic_sharpe_ratio(
    sharpe: float,
    observations: int,
    skew: float = 0.0,
    kurtosis: float = 3.0,
    benchmark: float = 0.0,
) -> float:
    """Probability the true Sharpe exceeds `benchmark`.

    `sharpe` and `benchmark` must be in the same (non-annualised) units as
    the observations they were computed from, or the result is meaningless.
    """
    if observations < 2:
        return 0.0
    variance = 1.0 - skew * sharpe + (kurtosis - 1.0) / 4.0 * sharpe**2
    if variance <= 0:
        return 0.0
    z = (sharpe - benchmark) * math.sqrt(observations - 1) / math.sqrt(variance)
    return float(stats.norm.cdf(z))


def expected_max_sharpe(trials: int, sharpe_variance: float = 1.0) -> float:
    """Sharpe the best of `trials` random strategies would show anyway.

    This is the benchmark a real strategy has to clear: with enough attempts,
    something always looks good.
    """
    if trials < 2:
        return 0.0
    e = math.e
    gaussian = float(stats.norm.ppf(1.0 - 1.0 / trials))
    gaussian_e = float(stats.norm.ppf(1.0 - 1.0 / (trials * e)))
    return math.sqrt(sharpe_variance) * (
        (1.0 - EULER_MASCHERONI) * gaussian + EULER_MASCHERONI * gaussian_e
    )


def deflated_sharpe_ratio(
    sharpe: float,
    observations: int,
    trials: int,
    skew: float = 0.0,
    kurtosis: float = 3.0,
    sharpe_variance: float = 1.0,
) -> float:
    """PSR against the Sharpe that `trials` attempts would produce by chance."""
    benchmark = expected_max_sharpe(trials, sharpe_variance)
    return probabilistic_sharpe_ratio(sharpe, observations, skew, kurtosis, benchmark)


@dataclass(frozen=True)
class NullComparison:
    """How a result compares with random entries over the same period."""

    samples: int
    observed: float
    null_median: float
    p_value: float
    trials: int
    family_adjusted_p: float

    def summary(self) -> str:
        return (
            f"  observed {self.observed * 100:+.2f}% vs random-entry median "
            f"{self.null_median * 100:+.2f}%\n"
            f"  p={self.p_value:.4f}; after correcting for {self.trials} "
            f"trials: p={self.family_adjusted_p:.3f}"
        )


def compare_with_null(
    observed: float,
    null_samples: np.ndarray | list[float],
    trials: int = 1,
) -> NullComparison:
    """Position a result within a distribution of random-entry results.

    The null must be built from entries drawn over the *same* calendar span:
    a strategy that only traded a bull market beats a null drawn from all
    history without having any edge at all.
    """
    samples = np.asarray(null_samples, dtype=np.float64)
    if len(samples) == 0:
        raise ValueError("null distribution is empty")
    # One-sided: how often chance alone does at least this well.
    exceedances = int(np.sum(samples >= observed))
    p_value = (exceedances + 1) / (len(samples) + 1)
    return NullComparison(
        samples=len(samples),
        observed=observed,
        null_median=float(np.median(samples)),
        p_value=p_value,
        trials=trials,
        family_adjusted_p=sidak_correction(p_value, trials),
    )
