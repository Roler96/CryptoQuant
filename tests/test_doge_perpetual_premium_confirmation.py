from __future__ import annotations

import numpy as np
import pytest

from cq.context import Context, Series
from research.explore_doge_perpetual_premium_confirmation import (
    SWAP_INSTRUMENT,
    DogePerpetualPremiumConfirmation,
    PpcParams,
)

FOUR_HOURS_MS = 4 * 60 * 60 * 1000


def _series(inst_id: str, close: np.ndarray) -> Series:
    return Series(
        inst_id=inst_id,
        timeframe="4h",
        ts=np.arange(len(close), dtype=np.int64) * FOUR_HOURS_MS,
        open=close,
        high=close * 1.001,
        low=close * 0.999,
        close=close,
        volume=np.full(len(close), 100.0),
    )


def _params(**overrides: object) -> PpcParams:
    values: dict[str, object] = {
        "premium_history": 8,
        "premium_block": 2,
        "premium_entry": 1.0,
        "premium_exit": 0.0,
        "momentum_bars": 3,
        "size": 0.25,
    }
    values.update(overrides)
    return PpcParams(**values)  # type: ignore[arg-type]


def _markets(extra_basis: list[float] | None = None) -> tuple[Series, Series]:
    basis = [
        -0.002,
        -0.001,
        0.000,
        0.001,
        0.002,
        -0.001,
        0.001,
        0.000,
        0.003,
        0.003,
    ]
    if extra_basis:
        basis.extend(extra_basis)
    spot = 100.0 * np.exp(np.arange(len(basis), dtype=float) * 0.01)
    swap = spot * np.exp(np.asarray(basis))
    return _series("DOGE-USDT", spot), _series(SWAP_INSTRUMENT, swap)


def test_positive_premium_and_momentum_enter_joint_state() -> None:
    spot, swap = _markets()
    strategy = DogePerpetualPremiumConfirmation(_params())
    ctx = Context(spot, aux=[swap])
    ctx.seek(len(spot) - 1)

    intent = strategy.on_bar(ctx)

    assert intent.target == pytest.approx(0.25)
    assert "ppc-joint" in intent.reason


def test_premium_normalization_excludes_the_current_block() -> None:
    spot_close = 100.0 * np.exp(np.arange(4, dtype=float) * 0.01)
    basis = np.asarray([-0.001, 0.001, 0.003, 0.003])
    spot = _series("DOGE-USDT", spot_close)
    swap = _series(SWAP_INSTRUMENT, spot_close * np.exp(basis))
    strategy = DogePerpetualPremiumConfirmation(
        PpcParams(
            premium_history=2,
            premium_block=2,
            premium_entry=1.5,
            momentum_bars=1,
        )
    )
    ctx = Context(spot, aux=[swap])
    ctx.seek(len(spot) - 1)

    # The non-overlapping baseline gives score 3.0. Polluting it with the
    # current block would give only 1.0 and fail this frozen threshold.
    assert strategy.on_bar(ctx).target == pytest.approx(0.25)


def test_signal_at_a_cursor_is_invariant_to_future_basis() -> None:
    prefix = _markets()
    full = _markets(extra_basis=[-0.20, 0.20])
    decision_index = len(prefix[0]) - 1
    prefix_ctx = Context(prefix[0], aux=[prefix[1]])
    full_ctx = Context(full[0], aux=[full[1]])
    prefix_ctx.seek(decision_index)
    full_ctx.seek(decision_index)

    prefix_intent = DogePerpetualPremiumConfirmation(_params()).on_bar(prefix_ctx)
    full_intent = DogePerpetualPremiumConfirmation(_params()).on_bar(full_ctx)

    assert prefix_intent == full_intent


def test_premium_reversion_exits_an_open_position() -> None:
    spot, swap = _markets(extra_basis=[0.0, 0.0])
    strategy = DogePerpetualPremiumConfirmation(_params())
    ctx = Context(spot, aux=[swap])
    signal_index = strategy.warmup_bars - 1

    targets: list[float] = []
    for index in range(signal_index, signal_index + 3):
        ctx.seek(index)
        targets.append(strategy.on_bar(ctx).target)

    assert targets == [0.25, 0.25, 0.0]


def test_momentum_only_does_not_require_a_nonzero_basis_mad() -> None:
    spot = 100.0 * np.exp(np.arange(10, dtype=float) * 0.01)
    primary = _series("DOGE-USDT", spot)
    swap = _series(SWAP_INSTRUMENT, spot.copy())
    strategy = DogePerpetualPremiumConfirmation(
        _params(use_premium=False, use_momentum=True)
    )
    ctx = Context(primary, aux=[swap])
    ctx.seek(len(primary) - 1)

    assert strategy.on_bar(ctx).target == pytest.approx(0.25)


def test_joint_state_refuses_a_zero_mad_basis() -> None:
    spot = 100.0 * np.exp(np.arange(10, dtype=float) * 0.01)
    primary = _series("DOGE-USDT", spot)
    swap = _series(SWAP_INSTRUMENT, spot.copy())
    ctx = Context(primary, aux=[swap])
    ctx.seek(len(primary) - 1)

    assert DogePerpetualPremiumConfirmation(_params()).on_bar(ctx).target == 0.0


def test_unaligned_swap_bar_cannot_create_an_entry() -> None:
    spot, swap = _markets()
    short_swap = _series(SWAP_INSTRUMENT, swap.close[:-1])
    strategy = DogePerpetualPremiumConfirmation(_params())
    ctx = Context(spot, aux=[short_swap])
    ctx.seek(len(spot) - 1)

    intent = strategy.on_bar(ctx)

    assert intent.target == 0.0
    assert intent.reason.endswith("unaligned")


def test_checkpoint_round_trip_and_configuration_guard() -> None:
    spot, swap = _markets()
    strategy = DogePerpetualPremiumConfirmation(_params())
    ctx = Context(spot, aux=[swap])
    ctx.seek(len(spot) - 1)
    strategy.on_bar(ctx)

    restored = DogePerpetualPremiumConfirmation(_params())
    restored.restore_state(strategy.snapshot_state())
    assert restored.snapshot_state() == strategy.snapshot_state()

    other = DogePerpetualPremiumConfirmation(_params(premium_entry=1.5))
    with pytest.raises(ValueError, match="configuration"):
        other.restore_state(strategy.snapshot_state())


@pytest.mark.parametrize(
    "kwargs",
    [
        {"premium_history": 1},
        {"premium_block": 0},
        {"premium_entry": 0.0},
        {"momentum_bars": 0},
        {"size": 0.0},
        {"use_premium": False, "use_momentum": False},
    ],
)
def test_parameter_validation(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _params(**kwargs)
