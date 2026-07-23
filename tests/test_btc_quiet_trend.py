from __future__ import annotations

import numpy as np
import pytest

from cq.context import Context, Series
from research.explore_btc_quiet_trend import (
    DISCOVERY_END,
    BqtParams,
    BtcQuietTrend,
    candidate_factories,
)

DAY_MS = 24 * 60 * 60 * 1000


def _series(returns: np.ndarray) -> Series:
    close = 100.0 * np.exp(np.r_[0.0, np.cumsum(np.asarray(returns, dtype=float))])
    return Series(
        inst_id="BTC-USDT",
        timeframe="1d",
        ts=np.arange(len(close), dtype=np.int64) * DAY_MS,
        open=close,
        high=close * 1.01,
        low=close * 0.99,
        close=close,
        volume=np.full(len(close), 100.0),
    )


def _quiet_uptrend(extra: int = 0) -> Series:
    baseline = np.tile(np.array([0.025, -0.015]), 126)
    quiet = np.full(20 + extra, 0.004)
    return _series(np.r_[baseline, quiet])


def _risky_tail() -> Series:
    baseline = np.tile(np.array([0.020, -0.010]), 126)
    risky = np.tile(np.array([0.040, -0.030]), 10)
    return _series(np.r_[baseline, risky])


def test_quiet_positive_trend_enters() -> None:
    series = _quiet_uptrend()
    ctx = Context(series)
    ctx.seek(len(series) - 1)

    intent = BtcQuietTrend().on_bar(ctx)

    assert intent.target == pytest.approx(1.0)


def test_high_downside_risk_blocks_entry() -> None:
    series = _risky_tail()
    ctx = Context(series)
    ctx.seek(len(series) - 1)

    intent = BtcQuietTrend().on_bar(ctx)

    assert intent.target == pytest.approx(0.0)


def test_risk_hysteresis_exits_an_existing_position() -> None:
    quiet = _quiet_uptrend()
    quiet_ctx = Context(quiet)
    quiet_ctx.seek(len(quiet) - 1)
    strategy = BtcQuietTrend()
    assert strategy.on_bar(quiet_ctx).target == pytest.approx(1.0)

    risky = _risky_tail()
    risky_ctx = Context(risky)
    risky_ctx.seek(len(risky) - 1)

    assert strategy.on_bar(risky_ctx).target == pytest.approx(0.0)


def test_signal_at_a_cursor_is_invariant_to_future_bars() -> None:
    prefix = _quiet_uptrend()
    full = _quiet_uptrend(extra=3)
    prefix_ctx = Context(prefix)
    full_ctx = Context(full)
    decision_index = len(prefix) - 1
    prefix_ctx.seek(decision_index)
    full_ctx.seek(decision_index)

    prefix_intent = BtcQuietTrend().on_bar(prefix_ctx)
    full_intent = BtcQuietTrend().on_bar(full_ctx)

    assert prefix_intent == full_intent


def test_momentum_ablation_does_not_require_risk_warmup() -> None:
    params = BqtParams(momentum_days=5, use_quiet=False)
    strategy = BtcQuietTrend(params)
    series = _series(np.full(5, 0.01))
    ctx = Context(series)
    ctx.seek(len(series) - 1)

    assert strategy.warmup_bars == 6
    assert strategy.on_bar(ctx).target == pytest.approx(1.0)


def test_checkpoint_round_trip_and_reset() -> None:
    series = _quiet_uptrend()
    ctx = Context(series)
    ctx.seek(len(series) - 1)
    strategy = BtcQuietTrend()
    strategy.on_bar(ctx)

    restored = BtcQuietTrend()
    restored.restore_state(strategy.snapshot_state())
    assert restored.snapshot_state() == strategy.snapshot_state()

    restored.reset()
    assert restored.snapshot_state()["target"] == pytest.approx(0.0)


def test_checkpoint_rejects_a_different_configuration() -> None:
    state = BtcQuietTrend().snapshot_state()
    other = BtcQuietTrend(BqtParams(momentum_days=60))

    with pytest.raises(ValueError, match="configuration"):
        other.restore_state(state)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("momentum_days", 1),
        ("downside_days", 1),
        ("baseline_days", 19),
        ("entry_quantile", 0.0),
        ("entry_quantile", 0.70),
        ("exit_quantile", 1.0),
        ("size", 0.0),
        ("size", 1.1),
    ],
)
def test_parameter_validation(field: str, value: float | int) -> None:
    with pytest.raises(ValueError):
        BqtParams(**{field: value})  # type: ignore[arg-type]


def test_registered_family_and_discovery_boundary_are_frozen() -> None:
    factories = candidate_factories()

    assert BtcQuietTrend().warmup_bars == 273
    assert DISCOVERY_END == "2025-06-01"
    assert set(factories) == {
        "main",
        "momentum_fast",
        "momentum_slow",
        "risk_fast",
        "risk_slow",
        "hysteresis_tight",
        "hysteresis_loose",
        "momentum_only",
        "quiet_only",
    }
