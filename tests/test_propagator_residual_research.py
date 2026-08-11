"""Unit tests for causal propagator-impact residual research features."""

from __future__ import annotations

import numpy as np
import pytest

from cq.context import Series
from cq.core.types import CostModel, MarketSpec, Sizing
from cq.engine.loop import run_backtest
from cq.research.propagator_residual import (
    PropagatorConfig,
    ResidualDecisionReplayStrategy,
    ResidualModel,
    ResidualReplayConfig,
    fit_residual_model,
    propagator_features,
    residual_target,
)

BAR_MS = 300_000


def test_tau_is_the_true_propagator_half_life() -> None:
    q = np.r_[1.0, np.zeros(12)]
    valid = np.ones(len(q), dtype=bool)

    state, _change = propagator_features(q, valid, tau=6, burn_in=0)

    assert state[6] == pytest.approx(0.5)
    assert state[12] == pytest.approx(0.25)


def test_invalid_bar_resets_state_and_requires_new_burn_in() -> None:
    q = np.ones(10)
    valid = np.ones(10, dtype=bool)
    valid[4] = False

    state, change = propagator_features(q, valid, tau=3, burn_in=2)

    assert np.isnan(state[4])
    assert np.isnan(change[4:7]).all()
    assert np.isfinite(change[7:]).all()


def test_causal_ols_recovers_intercept_slope_and_robust_scale() -> None:
    g = np.linspace(-1.0, 1.0, 101)
    noise = np.resize(np.array([-0.01, 0.01]), len(g))
    returns = 0.002 + 0.4 * g + noise

    model = fit_residual_model(g, returns)

    assert model is not None
    assert model.alpha == pytest.approx(0.002, abs=3e-4)
    assert model.beta == pytest.approx(0.4, abs=3e-3)
    assert model.sigma > 0.0


def test_residual_signal_reverses_a_flow_aligned_overshoot() -> None:
    config = PropagatorConfig(z_resid=3.0, predicted_share_floor=0.25)
    model = ResidualModel(alpha=0.0, beta=0.5, sigma=0.001)

    target = residual_target(
        current_return=0.010,
        propagator_change=0.010,
        activity_ratio=1.2,
        model=model,
        config=config,
    )

    assert target == -1.0


def test_residual_signal_rejects_low_activity_or_opposed_prediction() -> None:
    config = PropagatorConfig(z_resid=3.0, predicted_share_floor=0.25)
    model = ResidualModel(alpha=0.0, beta=0.5, sigma=0.001)

    assert (
        residual_target(
            current_return=0.010,
            propagator_change=0.010,
            activity_ratio=0.9,
            model=model,
            config=config,
        )
        == 0.0
    )
    assert (
        residual_target(
            current_return=0.010,
            propagator_change=-0.010,
            activity_ratio=1.2,
            model=model,
            config=config,
        )
        == 0.0
    )


def test_config_rejects_invalid_values() -> None:
    constructors = (
        lambda: PropagatorConfig(flow_window=1),
        lambda: PropagatorConfig(regression_window=2),
        lambda: PropagatorConfig(tau=0),
        lambda: PropagatorConfig(z_resid=0.0),
        lambda: PropagatorConfig(predicted_share_floor=1.1),
        lambda: PropagatorConfig(hold_bars=0),
        lambda: PropagatorConfig(target_weight=1.1),
    )
    for constructor in constructors:
        with pytest.raises(ValueError):
            constructor()


def test_decision_replay_uses_next_open_and_exact_hold() -> None:
    prices = np.linspace(100.0, 103.0, 30)
    series = Series(
        "DOGE-USDT-SWAP",
        "5m",
        np.arange(len(prices), dtype=np.int64) * BAR_MS,
        prices,
        prices,
        prices,
        prices,
        np.ones(len(prices)),
    )
    result = run_backtest(
        ResidualDecisionReplayStrategy(
            frozenset({5 * BAR_MS}),
            ResidualReplayConfig(
                hold_bars=12,
                evaluation_end_ms=len(prices) * BAR_MS,
            ),
        ),
        series,
        MarketSpec("DOGE-USDT-SWAP", "swap", maintenance_margin_rate=0.0),
        costs=CostModel(fee_bps=0.0, slippage_bps=0.0),
        sizing=Sizing.ON_ENTRY,
        dust_fraction=0.0,
    )

    assert [fill.ts for fill in result.fills] == [6 * BAR_MS, 18 * BAR_MS]
    assert result.rejections == []
    assert result.portfolio.is_flat
