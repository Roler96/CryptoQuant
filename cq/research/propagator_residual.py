"""Causal features for propagator-impact residual decay research."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from cq.context import Context
from cq.core.clock import duration_ms
from cq.core.types import FLAT, Intent


@dataclass(frozen=True)
class PropagatorConfig:
    flow_window: int = 288
    regression_window: int = 2016
    tau: int = 6
    z_resid: float = 3.0
    predicted_share_floor: float = 0.25
    hold_bars: int = 12
    target_weight: float = 0.25

    def __post_init__(self) -> None:
        if self.flow_window < 2:
            raise ValueError("flow_window must be at least two")
        if self.regression_window < 3:
            raise ValueError("regression_window must be at least three")
        if self.tau <= 0:
            raise ValueError("tau must be positive")
        if not math.isfinite(self.z_resid) or self.z_resid <= 0.0:
            raise ValueError("z_resid must be finite and positive")
        if not 0.0 < self.predicted_share_floor <= 1.0:
            raise ValueError("predicted_share_floor must be in (0, 1]")
        if self.hold_bars <= 0:
            raise ValueError("hold_bars must be positive")
        if not 0.0 < self.target_weight <= 1.0:
            raise ValueError("target_weight must be in (0, 1]")


@dataclass(frozen=True)
class ResidualModel:
    alpha: float
    beta: float
    sigma: float


@dataclass(frozen=True)
class ResidualReplayConfig:
    hold_bars: int = 12
    target_weight: float = 0.25
    evaluation_end_ms: int = 2**63 - 1

    def __post_init__(self) -> None:
        if self.hold_bars <= 0:
            raise ValueError("hold_bars must be positive")
        if not 0.0 < self.target_weight <= 1.0:
            raise ValueError("target_weight must be in (0, 1]")


class ResidualDecisionReplayStrategy:
    """Replay causally precomputed PIRD decisions through the shared engine."""

    name = "doge-pird-downside-residual-replay"

    def __init__(
        self,
        decision_times: frozenset[int],
        config: ResidualReplayConfig | None = None,
    ):
        self.decision_times = decision_times
        self.config = config or ResidualReplayConfig()
        self._remaining = 0

    @property
    def warmup_bars(self) -> int:
        return 1

    def reset(self) -> None:
        self._remaining = 0

    def on_bar(self, ctx: Context) -> Intent:
        if self._remaining > 1:
            self._remaining -= 1
            return Intent(target=self.config.target_weight, reason="pird-replay-hold")
        if self._remaining == 1:
            self.reset()
            return Intent(target=0.0, reason="pird-replay-time-exit")

        bar_ms = duration_ms(ctx.primary.timeframe)
        exit_time = ctx.decision_time + self.config.hold_bars * bar_ms
        if exit_time >= self.config.evaluation_end_ms:
            return FLAT
        if ctx.now not in self.decision_times:
            return FLAT
        self._remaining = self.config.hold_bars
        return Intent(target=self.config.target_weight, reason="pird-downside-residual")


def propagator_features(
    flow: np.ndarray,
    valid: np.ndarray,
    *,
    tau: int,
    burn_in: int | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Build exponentially decaying impact state and its first difference."""
    values = np.asarray(flow, dtype=float)
    valid_values = np.asarray(valid, dtype=bool)
    if values.ndim != 1 or valid_values.ndim != 1 or len(values) != len(valid_values):
        raise ValueError("flow and valid must be same-length one-dimensional arrays")
    if tau <= 0:
        raise ValueError("tau must be positive")
    burn = math.ceil(5 * tau) if burn_in is None else burn_in
    if burn < 0:
        raise ValueError("burn_in must be non-negative")

    state = np.full(len(values), np.nan, dtype=float)
    change = np.full(len(values), np.nan, dtype=float)
    decay = 2.0 ** (-1.0 / float(tau))
    impact = 0.0
    valid_run = 0
    for index, value in enumerate(values):
        if not valid_values[index] or not math.isfinite(float(value)):
            impact = 0.0
            valid_run = 0
            continue
        previous = impact
        impact = decay * previous + float(value)
        state[index] = impact
        valid_run += 1
        if valid_run > burn:
            change[index] = impact - previous
    return state, change


def fit_residual_model(
    propagator_change: np.ndarray,
    returns: np.ndarray,
) -> ResidualModel | None:
    """Fit OLS with intercept and a robust residual MAD scale."""
    g = np.asarray(propagator_change, dtype=float)
    r = np.asarray(returns, dtype=float)
    if g.ndim != 1 or r.ndim != 1 or len(g) != len(r):
        raise ValueError("propagator_change and returns must be same-length vectors")
    if len(g) < 3 or not np.isfinite(g).all() or not np.isfinite(r).all():
        return None
    centered_g = g - float(np.mean(g))
    denominator = float(np.dot(centered_g, centered_g))
    if denominator <= 0.0 or not math.isfinite(denominator):
        return None
    centered_r = r - float(np.mean(r))
    beta = float(np.dot(centered_g, centered_r) / denominator)
    alpha = float(np.mean(r) - beta * np.mean(g))
    residuals = r - alpha - beta * g
    residual_median = float(np.median(residuals))
    sigma = float(1.4826 * np.median(np.abs(residuals - residual_median)))
    if not all(math.isfinite(value) for value in (alpha, beta, sigma)) or sigma <= 0.0:
        return None
    return ResidualModel(alpha=alpha, beta=beta, sigma=sigma)


def residual_target(
    *,
    current_return: float,
    propagator_change: float,
    activity_ratio: float,
    model: ResidualModel,
    config: PropagatorConfig,
) -> float:
    """Return the reversal direction for a flow-aligned residual overshoot."""
    values = (
        current_return,
        propagator_change,
        activity_ratio,
        model.alpha,
        model.beta,
        model.sigma,
    )
    if not all(math.isfinite(value) for value in values):
        return 0.0
    if model.beta <= 0.0 or model.sigma <= 0.0 or activity_ratio < 1.0:
        return 0.0
    predicted = model.alpha + model.beta * propagator_change
    residual = current_return - predicted
    if current_return == 0.0 or predicted == 0.0 or residual == 0.0:
        return 0.0
    if abs(residual) / model.sigma < config.z_resid:
        return 0.0
    direction = math.copysign(1.0, current_return)
    if math.copysign(1.0, predicted) != direction:
        return 0.0
    if math.copysign(1.0, residual) != direction:
        return 0.0
    if abs(predicted) / abs(current_return) < config.predicted_share_floor:
        return 0.0
    return -direction
