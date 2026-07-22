from __future__ import annotations

import numpy as np
import pytest

from cq.context import Context, Series
from research.explore_doge_dual_leader_catchup import (
    BTC_INSTRUMENT,
    ETH_INSTRUMENT,
    DlcParams,
    DogeDualLeaderCatchup,
)

HOUR_MS = 60 * 60 * 1000


def _series(inst_id: str, returns: list[float]) -> Series:
    close = 100.0 * np.exp(np.r_[0.0, np.cumsum(np.asarray(returns))])
    return Series(
        inst_id=inst_id,
        timeframe="1h",
        ts=np.arange(len(close), dtype=np.int64) * HOUR_MS,
        open=close,
        high=close * 1.001,
        low=close * 0.999,
        close=close,
        volume=np.full(len(close), 100.0),
    )


def _params() -> DlcParams:
    return DlcParams(
        shock_hours=2,
        beta_history=6,
        leader_history=12,
        leader_quantile=0.80,
        hold_hours=3,
        cooldown_hours=6,
    )


def _paths(extra: int = 0) -> tuple[Series, Series, Series]:
    leader = [
        0.006,
        -0.004,
        0.005,
        -0.003,
        0.004,
        -0.005,
        0.006,
        -0.004,
        0.005,
        -0.003,
        0.004,
        -0.002,
        0.050,
        0.040,
    ] + [0.0] * extra
    doge = [value * 1.5 for value in leader[:12]] + [0.005, 0.002] + [0.0] * extra
    return (
        _series("DOGE-USDT", doge),
        _series(BTC_INSTRUMENT, leader),
        _series(ETH_INSTRUMENT, leader),
    )


def test_dual_leader_lag_with_positive_confirmation_enters() -> None:
    doge, btc, eth = _paths()
    strategy = DogeDualLeaderCatchup(_params())
    ctx = Context(doge, aux=[btc, eth])
    ctx.seek(len(doge) - 1)

    intent = strategy.on_bar(ctx)

    assert intent.target == pytest.approx(0.25)
    assert "lagging-confirmed" in intent.reason


def test_signal_at_a_cursor_is_invariant_to_future_bars() -> None:
    prefix = _paths()
    full = _paths(extra=3)
    prefix_ctx = Context(prefix[0], aux=prefix[1:])
    full_ctx = Context(full[0], aux=full[1:])
    decision_index = len(prefix[0]) - 1
    prefix_ctx.seek(decision_index)
    full_ctx.seek(decision_index)

    prefix_intent = DogeDualLeaderCatchup(_params()).on_bar(prefix_ctx)
    full_intent = DogeDualLeaderCatchup(_params()).on_bar(full_ctx)

    assert prefix_intent == full_intent


def test_frozen_hold_exits_after_three_complete_hours() -> None:
    doge, btc, eth = _paths(extra=3)
    strategy = DogeDualLeaderCatchup(_params())
    ctx = Context(doge, aux=[btc, eth])
    signal_index = strategy.warmup_bars - 1

    targets: list[float] = []
    for index in range(signal_index, signal_index + 4):
        ctx.seek(index)
        targets.append(strategy.on_bar(ctx).target)

    assert targets == [0.25, 0.25, 0.25, 0.0]


def test_checkpoint_round_trip_preserves_open_position_and_cooldown() -> None:
    doge, btc, eth = _paths()
    strategy = DogeDualLeaderCatchup(_params())
    ctx = Context(doge, aux=[btc, eth])
    ctx.seek(len(doge) - 1)
    strategy.on_bar(ctx)

    restored = DogeDualLeaderCatchup(_params())
    restored.restore_state(strategy.snapshot_state())

    assert restored.snapshot_state() == strategy.snapshot_state()


def test_checkpoint_rejects_state_from_a_different_candidate() -> None:
    state = DogeDualLeaderCatchup(_params()).snapshot_state()
    other = DogeDualLeaderCatchup(
        DlcParams(
            shock_hours=2,
            beta_history=6,
            leader_history=12,
            leader_quantile=0.90,
            hold_hours=3,
            cooldown_hours=6,
        )
    )

    with pytest.raises(ValueError, match="configuration"):
        other.restore_state(state)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("shock_hours", 0),
        ("beta_history", 1),
        ("leader_history", 1),
        ("leader_quantile", 1.0),
        ("hold_hours", 0),
        ("cooldown_hours", 11),
        ("size", 0.0),
    ],
)
def test_parameter_validation(field: str, value: float | int) -> None:
    kwargs: dict[str, float | int] = {field: value}
    if field == "cooldown_hours":
        kwargs["hold_hours"] = 12
    with pytest.raises(ValueError):
        DlcParams(**kwargs)  # type: ignore[arg-type]
