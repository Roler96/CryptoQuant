from __future__ import annotations

import numpy as np
import pytest

from cq.context import Context, Series
from research.explore_doge_dual_leader_catchup import BTC_INSTRUMENT, ETH_INSTRUMENT
from research.explore_doge_idiosyncratic_selloff_reversal import (
    DogeIdiosyncraticSelloffReversal,
    IsrParams,
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


def _params(**overrides: object) -> IsrParams:
    values: dict[str, object] = {
        "shock_hours": 2,
        "beta_history": 12,
        "hold_hours": 3,
        "cooldown_after_exit": 4,
    }
    values.update(overrides)
    return IsrParams(**values)  # type: ignore[arg-type]


def _paths(
    *, current_market: tuple[float, float] = (0.005, 0.005), extra: int = 0
) -> tuple[Series, Series, Series]:
    calibration_market = [0.01, -0.01] * 6
    market = calibration_market + list(current_market) + [0.0] * extra
    doge = [1.5 * value for value in calibration_market] + [-0.03, 0.005]
    doge += [0.0] * extra
    return (
        _series("DOGE-USDT", doge),
        _series(BTC_INSTRUMENT, market),
        _series(ETH_INSTRUMENT, market),
    )


def test_extreme_specific_selloff_with_positive_confirmation_enters() -> None:
    doge, btc, eth = _paths()
    strategy = DogeIdiosyncraticSelloffReversal(_params())
    ctx = Context(doge, aux=[btc, eth])
    ctx.seek(len(doge) - 1)

    intent = strategy.on_bar(ctx)

    assert intent.target == pytest.approx(0.25)
    assert "tail-market-up-confirmed" in intent.reason


def test_signal_is_prefix_invariant_to_future_bars() -> None:
    prefix = _paths()
    full = _paths(extra=4)
    prefix_ctx = Context(prefix[0], aux=prefix[1:])
    full_ctx = Context(full[0], aux=full[1:])
    decision = len(prefix[0]) - 1
    prefix_ctx.seek(decision)
    full_ctx.seek(decision)

    prefix_intent = DogeIdiosyncraticSelloffReversal(_params()).on_bar(prefix_ctx)
    full_intent = DogeIdiosyncraticSelloffReversal(_params()).on_bar(full_ctx)

    assert prefix_intent == full_intent


def test_market_filter_blocks_a_marketwide_downturn() -> None:
    doge, btc, eth = _paths(current_market=(-0.005, -0.005))
    ctx = Context(doge, aux=[btc, eth])
    ctx.seek(len(doge) - 1)

    main = DogeIdiosyncraticSelloffReversal(_params()).on_bar(ctx)
    ablation = DogeIdiosyncraticSelloffReversal(
        _params(require_market_nonnegative=False)
    ).on_bar(ctx)

    assert main.target == 0.0
    assert ablation.target == pytest.approx(0.25)


def test_plain_reversal_can_enter_without_a_tail_residual() -> None:
    doge, btc, eth = _paths(current_market=(-0.10, -0.10))
    ctx = Context(doge, aux=[btc, eth])
    ctx.seek(len(doge) - 1)

    plain = DogeIdiosyncraticSelloffReversal(
        _params(residual_mode="none", require_market_nonnegative=False)
    ).on_bar(ctx)

    assert plain.target == pytest.approx(0.25)


def test_hold_and_post_exit_cooldown_are_frozen() -> None:
    doge, btc, eth = _paths(extra=8)
    strategy = DogeIdiosyncraticSelloffReversal(_params())
    ctx = Context(doge, aux=[btc, eth])
    signal_index = strategy.warmup_bars - 1

    targets = []
    for index in range(signal_index, signal_index + 8):
        ctx.seek(index)
        targets.append(strategy.on_bar(ctx).target)

    assert targets[:4] == [0.25, 0.25, 0.25, 0.0]
    assert targets[4:] == [0.0, 0.0, 0.0, 0.0]
    assert strategy.snapshot_state()["blocked_until"] == signal_index + 7


def test_checkpoint_round_trip_preserves_position_and_cooldown() -> None:
    doge, btc, eth = _paths()
    strategy = DogeIdiosyncraticSelloffReversal(_params())
    ctx = Context(doge, aux=[btc, eth])
    ctx.seek(len(doge) - 1)
    strategy.on_bar(ctx)

    restored = DogeIdiosyncraticSelloffReversal(_params())
    restored.restore_state(strategy.snapshot_state())

    assert restored.snapshot_state() == strategy.snapshot_state()


def test_checkpoint_rejects_a_different_formula() -> None:
    state = DogeIdiosyncraticSelloffReversal(_params()).snapshot_state()
    other = DogeIdiosyncraticSelloffReversal(_params(residual_quantile=0.10))

    with pytest.raises(ValueError, match="configuration"):
        other.restore_state(state)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("shock_hours", 0),
        ("beta_history", 1),
        ("residual_quantile", 1.0),
        ("hold_hours", 0),
        ("cooldown_after_exit", -1),
        ("size", 0.0),
        ("residual_mode", "opposite"),
    ],
)
def test_parameter_validation(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        _params(**{field: value})
