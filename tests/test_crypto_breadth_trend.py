from __future__ import annotations

import numpy as np
import pytest

from cq.context import Context, Series
from research.explore_crypto_breadth_trend import (
    DISCOVERY_END,
    DOGE_INSTRUMENT,
    ETH_INSTRUMENT,
    CbtParams,
    CryptoBreadthTrend,
    candidate_factories,
)

DAY_MS = 24 * 60 * 60 * 1000


def _series(inst_id: str, close: np.ndarray, shift_days: int = 0) -> Series:
    values = np.asarray(close, dtype=float)
    return Series(
        inst_id=inst_id,
        timeframe="1d",
        ts=(np.arange(len(values), dtype=np.int64) + shift_days) * DAY_MS,
        open=values,
        high=values * 1.01,
        low=values * 0.99,
        close=values,
        volume=np.full(len(values), 100.0),
    )


def _paths(
    btc: np.ndarray,
    eth: np.ndarray,
    doge: np.ndarray,
) -> tuple[Series, Series, Series]:
    return (
        _series("BTC-USDT", btc),
        _series(ETH_INSTRUMENT, eth),
        _series(DOGE_INSTRUMENT, doge),
    )


def test_two_asset_breadth_and_btc_trend_enter() -> None:
    paths = _paths(
        np.linspace(100.0, 200.0, 220),
        np.linspace(100.0, 140.0, 220),
        np.linspace(100.0, 80.0, 220),
    )
    ctx = Context(paths[0], aux=paths[1:])
    ctx.seek(len(paths[0]) - 1)

    intent = CryptoBreadthTrend().on_bar(ctx)

    assert intent.target == pytest.approx(1.0)


def test_btc_trend_without_cross_asset_breadth_stays_in_cash() -> None:
    paths = _paths(
        np.linspace(100.0, 200.0, 220),
        np.linspace(140.0, 100.0, 220),
        np.linspace(120.0, 80.0, 220),
    )
    ctx = Context(paths[0], aux=paths[1:])
    ctx.seek(len(paths[0]) - 1)

    intent = CryptoBreadthTrend().on_bar(ctx)

    assert intent.target == pytest.approx(0.0)


def test_breadth_without_btc_trend_stays_in_cash() -> None:
    paths = _paths(
        np.linspace(200.0, 100.0, 220),
        np.linspace(100.0, 140.0, 220),
        np.linspace(80.0, 120.0, 220),
    )
    ctx = Context(paths[0], aux=paths[1:])
    ctx.seek(len(paths[0]) - 1)

    intent = CryptoBreadthTrend().on_bar(ctx)

    assert intent.target == pytest.approx(0.0)


def test_signal_at_a_cursor_is_invariant_to_future_bars() -> None:
    prefix = _paths(
        np.linspace(100.0, 200.0, 220),
        np.linspace(100.0, 140.0, 220),
        np.linspace(100.0, 80.0, 220),
    )
    full = _paths(
        np.r_[prefix[0].close, [500.0, 10.0]],
        np.r_[prefix[1].close, [5.0, 600.0]],
        np.r_[prefix[2].close, [900.0, 1.0]],
    )
    prefix_ctx = Context(prefix[0], aux=prefix[1:])
    full_ctx = Context(full[0], aux=full[1:])
    decision_index = len(prefix[0]) - 1
    prefix_ctx.seek(decision_index)
    full_ctx.seek(decision_index)

    prefix_intent = CryptoBreadthTrend().on_bar(prefix_ctx)
    full_intent = CryptoBreadthTrend().on_bar(full_ctx)

    assert prefix_intent == full_intent


def test_stale_auxiliary_daily_bar_cannot_confirm_breadth() -> None:
    primary = _series("BTC-USDT", np.linspace(100.0, 200.0, 220))
    eth = _series(ETH_INSTRUMENT, np.linspace(100.0, 140.0, 218))
    doge = _series(DOGE_INSTRUMENT, np.linspace(100.0, 140.0, 220))
    ctx = Context(primary, aux=[eth, doge])
    ctx.seek(len(primary) - 1)

    intent = CryptoBreadthTrend().on_bar(ctx)

    assert intent.target == pytest.approx(0.0)
    assert intent.reason.endswith("aux-unaligned")


def test_checkpoint_round_trip_and_reset() -> None:
    paths = _paths(
        np.linspace(100.0, 200.0, 220),
        np.linspace(100.0, 140.0, 220),
        np.linspace(100.0, 80.0, 220),
    )
    strategy = CryptoBreadthTrend()
    ctx = Context(paths[0], aux=paths[1:])
    ctx.seek(len(paths[0]) - 1)
    strategy.on_bar(ctx)

    restored = CryptoBreadthTrend()
    restored.restore_state(strategy.snapshot_state())
    assert restored.snapshot_state() == strategy.snapshot_state()

    restored.reset()
    assert restored.snapshot_state()["target"] == pytest.approx(0.0)


def test_checkpoint_rejects_a_different_configuration() -> None:
    state = CryptoBreadthTrend().snapshot_state()
    other = CryptoBreadthTrend(CbtParams(momentum_days=42))

    with pytest.raises(ValueError, match="configuration"):
        other.restore_state(state)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("momentum_days", 1),
        ("trend_days", 1),
        ("min_breadth", 0),
        ("min_breadth", 4),
        ("size", 0.0),
        ("size", 1.1),
    ],
)
def test_parameter_validation(field: str, value: float | int) -> None:
    with pytest.raises(ValueError):
        CbtParams(**{field: value})  # type: ignore[arg-type]


def test_registered_family_and_discovery_boundary_are_frozen() -> None:
    factories = candidate_factories()

    assert DISCOVERY_END == "2025-06-01"
    assert set(factories) == {
        "main",
        "momentum_fast",
        "momentum_slow",
        "trend_fast",
        "trend_slow",
        "btc_trend_only",
        "breadth_only",
    }
