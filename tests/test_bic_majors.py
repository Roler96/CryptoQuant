"""Synthetic-bar tests for the frozen BIC-Majors v1 strategy.

Every series is synthetic and built to exercise one frozen rule at a time.
Timestamp gaps abort the run because the engine's pending-order semantics
cannot reproduce the protocol's exact next-open behavior without framework
changes.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from cq.context import Context, Series
from cq.core.types import MarketSpec, Side, TradingError
from cq.engine.loop import run_backtest
from cq.strategy.bic_majors import (
    BAR_MS,
    FAMILY_TRIALS,
    FROZEN_VERSIONS,
    BicConfig,
    BicMajors,
)

SPEC = MarketSpec("BTC-USDT-SWAP", "swap")
T0 = 1_600_000_000_000
BASELINE = 168
# Baseline bars alternate by this ratio, so every baseline |r| is identical and
# the trailing q99 is a known constant rather than an artefact of the sample.
TICK = 1.001
QUIET = abs(math.log(TICK))
# Impulse multipliers. Powers of two keep the quiet returns exact across a
# jump; see `_series`.
UP = 2.0
DOWN = 0.5

E = BASELINE + 4  # signal bar index used by most scenarios


def _series(
    n: int,
    impulses: dict[int, float] | None = None,
    *,
    inst_id: str = "BTC-USDT-SWAP",
    overrides: dict[int, dict[str, float]] | None = None,
    drop: tuple[int, ...] = (),
) -> Series:
    """Alternating quiet bars, with a multiplicative jump at each impulse index.

    Impulses are given as price multipliers and the tests use powers of two.
    That is not cosmetic: scaling a level by a power of two only changes the
    float's exponent, so every quiet return is computed bit-for-bit the same
    before and after an impulse. With a ragged multiplier the post-impulse
    rounding drifts by an ulp, which is enough to push a quiet bar past a
    threshold made of its own supposedly identical neighbours.

    `drop` removes rows after the columns are built, so a dropped index leaves
    a genuine timestamp gap rather than a shifted series.
    """
    closes = np.empty(n)
    level = 1.0
    for i in range(n):
        if impulses and i in impulses:
            level *= impulses[i]
        closes[i] = level * (TICK if i % 2 else 1.0)

    columns = {
        "open": closes.copy(),
        "high": closes * 1.0005,
        "low": closes * 0.9995,
        "close": closes,
        "volume": np.full(n, 100.0),
    }
    for index, fields in (overrides or {}).items():
        for name, value in fields.items():
            columns[name][index] = value
    ts = T0 + np.arange(n, dtype=np.int64) * BAR_MS
    if drop:
        keep = np.ones(n, dtype=bool)
        keep[list(drop)] = False
        ts = ts[keep]
        columns = {name: column[keep] for name, column in columns.items()}
    return Series(inst_id, "1h", ts, **columns)


def _targets(strategy: BicMajors, series: Series) -> np.ndarray:
    context = Context(series)
    targets = np.zeros(len(series), dtype=float)
    for index in range(len(series)):
        context.seek(index)
        targets[index] = strategy.on_bar(context).target
    return targets


# ---- direction -------------------------------------------------------


def test_up_impulse_goes_long_and_holds_twelve_bars() -> None:
    series = _series(E + 40, {E: UP})
    targets = _targets(BicMajors(), series)
    assert np.all(targets[:E] == 0.0)
    assert np.all(targets[E : E + 12] == 0.25)
    assert np.all(targets[E + 12 :] == 0.0)


def test_down_impulse_goes_short() -> None:
    """The whole point: BTC continues, so a down-impulse is sold, not bought."""
    series = _series(E + 40, {E: DOWN})
    targets = _targets(BicMajors(), series)
    assert np.all(targets[E : E + 12] == -0.25)
    assert np.all(targets[E + 12 :] == 0.0)


def test_return_at_threshold_does_not_fire() -> None:
    # Strictly greater: a return exactly at the trailing quantile is not an
    # impulse. The alternating baseline makes that quantile exactly QUIET.
    series = _series(E + 40, {E: 1.0})
    targets = _targets(BicMajors(), series)
    assert np.all(targets == 0.0)


def test_small_impulse_below_quantile_does_not_fire() -> None:
    series = _series(E + 40, {E: math.exp(QUIET * 0.5)})
    targets = _targets(BicMajors(), series)
    assert np.all(targets == 0.0)


# ---- the lookahead that matters --------------------------------------


def test_signal_bar_never_enters_its_own_baseline() -> None:
    """The current bar must not raise the bar it is judged against.

    Two earlier impulses sit inside the trailing window. With them plus the
    signal bar, three of 169 samples are large and the q99 lands *on* a large
    value, so an implementation that included the current bar would compute a
    threshold equal to the signal itself and refuse to fire. Excluding it
    leaves two large values among 168, the q99 interpolates far below, and the
    signal fires. Only the correct implementation fires here.
    """
    strategy = BicMajors()
    series = _series(E + 40, {E - 100: UP, E - 99: UP, E: UP})
    context = Context(series)
    context.seek(E)
    assert strategy._signal(context) == 1.0

    # Confirm the discriminating power of the construction: had the current
    # bar been included, the threshold would have equalled the signal itself.
    closes = series.close[: E + 1]
    returns = np.diff(np.log(closes[-(BASELINE + 2) :]))
    with_current = float(np.quantile(np.abs(returns), 0.99))
    without_current = float(np.quantile(np.abs(returns[:-1]), 0.99))
    assert abs(returns[-1]) <= with_current
    assert abs(returns[-1]) > without_current


def test_warmup_bars_covers_the_baseline_and_its_difference() -> None:
    strategy = BicMajors()
    assert strategy.warmup_bars == BASELINE + 2
    # One bar short of warmup cannot fire even on a huge move.
    series = _series(BASELINE + 40, {BASELINE: UP})
    targets = _targets(BicMajors(), series)
    assert targets[BASELINE] == 0.0


# ---- state machine ---------------------------------------------------


def test_cooldown_blocks_a_second_signal() -> None:
    # Exit fills at E+13; the cooldown runs 12 bars from that fill, so an
    # impulse at E+20 is inside it and an impulse at E+26 is not.
    blocked = _targets(BicMajors(), _series(E + 60, {E: UP, E + 20: UP}))
    assert np.all(blocked[E + 12 : E + 26] == 0.0)

    allowed = _targets(BicMajors(), _series(E + 60, {E: UP, E + 26: UP}))
    assert np.all(allowed[E + 26 : E + 38] == 0.25)


def test_entry_and_exit_fill_at_planned_opens() -> None:
    series = _series(E + 40, {E: UP})
    result = run_backtest(BicMajors(), series, SPEC, 10_000.0)
    assert [fill.side for fill in result.fills] == [Side.BUY, Side.SELL]
    buy, sell = result.fills
    # Decided on E's close, filled at E+1's open; exit decided on the close of
    # the 12th held bar (E+12), filled at E+13's open.
    assert buy.ts == int(series.ts[E + 1])
    assert sell.ts == int(series.ts[E + 13])


def test_short_episode_sells_then_buys_back() -> None:
    series = _series(E + 40, {E: DOWN})
    result = run_backtest(BicMajors(), series, SPEC, 10_000.0)
    assert [fill.side for fill in result.fills] == [Side.SELL, Side.BUY]


def test_zero_volume_entry_bar_voids_event_without_chasing() -> None:
    # The engine keeps a rejected order pending for the next open; the strategy
    # must overwrite it the moment it sees the untradeable entry bar, so a
    # tradeable E+2 gets no fill at all.
    series = _series(E + 40, {E: UP}, overrides={E + 1: {"volume": 0.0}})
    strategy = BicMajors()
    result = run_backtest(strategy, series, SPEC, 10_000.0)
    assert result.fills == []
    assert strategy.accepted_events == 1
    assert strategy.voided_entries == 1
    assert strategy.completed_episodes == 0


def test_zero_volume_signal_bar_cannot_be_an_impulse() -> None:
    """An untradeable bar is not an event, whatever its return looks like.

    The assertion stops at the signal bar on purpose. Once a 69% jump is in
    the trailing window it shifts the quantile onto a neighbouring sample, and
    since a synthetic series' up and down moves differ by an ulp
    (`log(1.001)` against `|log(1/1.001)|`), a later quiet bar can land on the
    wrong side of the threshold. That is an artefact of the fixture, not
    behaviour worth pinning, and asserting on it would be asserting on
    floating-point noise.
    """
    strategy = BicMajors()
    series = _series(E + 40, {E: UP}, overrides={E: {"volume": 0.0}})
    context = Context(series)
    target = 0.0
    for index in range(E + 1):
        context.seek(index)
        target = strategy.on_bar(context).target
    assert target == 0.0
    assert strategy.accepted_events == 0


def test_timestamp_gap_aborts_the_run() -> None:
    series = _series(E + 40, {E: UP}, drop=(E - 2,))
    with pytest.raises(ValueError, match="contiguous"):
        _targets(BicMajors(), series)


def test_event_counters_split_by_direction() -> None:
    strategy = BicMajors()
    _targets(strategy, _series(E + 80, {E: UP, E + 40: DOWN}))
    assert strategy.accepted_events == 2
    assert strategy.long_events == 1
    assert strategy.short_events == 1
    assert strategy.completed_episodes == 2


# ---- instrument binding and both legs --------------------------------


def test_spot_market_refuses_the_short_leg() -> None:
    """A spot spec must reject the short rather than silently flatten it."""
    series = _series(E + 40, {E: DOWN}, inst_id="BTC-USDT-SWAP")
    with pytest.raises(TradingError, match="cannot hold a short target"):
        run_backtest(BicMajors(), series, MarketSpec("BTC-USDT-SWAP", "spot"), 10_000.0)


def test_instance_is_bound_to_its_instrument() -> None:
    strategy = BicMajors(inst_id="ETH-USDT-SWAP")
    with pytest.raises(ValueError, match="bound to"):
        _targets(strategy, _series(E + 40, {E: UP}, inst_id="BTC-USDT-SWAP"))


def test_unfrozen_instrument_is_rejected() -> None:
    with pytest.raises(ValueError, match="frozen for"):
        BicMajors(inst_id="DOGE-USDT-SWAP")


def test_both_legs_run_the_identical_configuration() -> None:
    btc = BicMajors(inst_id="BTC-USDT-SWAP")
    eth = BicMajors(inst_id="ETH-USDT-SWAP")
    assert btc.config == eth.config

    # Same bars, different instrument label: the legs must agree bar for bar,
    # because no parameter is allowed to depend on the asset.
    btc_targets = _targets(btc, _series(E + 40, {E: UP}))
    eth_targets = _targets(eth, _series(E + 40, {E: UP}, inst_id="ETH-USDT-SWAP"))
    assert np.array_equal(btc_targets, eth_targets)


def test_wrong_timeframe_is_rejected() -> None:
    series = Series(
        "BTC-USDT-SWAP",
        "5m",
        T0 + np.arange(10, dtype=np.int64) * 300_000,
        open=np.ones(10),
        high=np.ones(10),
        low=np.ones(10),
        close=np.ones(10),
        volume=np.full(10, 100.0),
    )
    with pytest.raises(ValueError, match="native-1h"):
        _targets(BicMajors(), series)


# ---- frozen family ---------------------------------------------------


def test_family_is_main_plus_six_one_axis_neighbours() -> None:
    assert FAMILY_TRIALS == 7
    main = FROZEN_VERSIONS["main"]
    assert main == BicConfig()
    for name, config in FROZEN_VERSIONS.items():
        if name == "main":
            continue
        differing = [
            field
            for field in ("quantile", "hold_bars", "baseline_bars", "cooldown_bars")
            if getattr(config, field) != getattr(main, field)
        ]
        assert differing == [differing[0]], f"{name} varies on more than one axis"
        assert config.target_weight == main.target_weight


def test_configuration_outside_the_family_is_rejected() -> None:
    with pytest.raises(ValueError, match="pre-registered"):
        BicMajors(BicConfig(hold_bars=13))


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({"quantile": 1.0}, id="quantile-not-below-one"),
        pytest.param({"quantile": 0.4}, id="quantile-not-a-tail"),
        pytest.param({"hold_bars": 0}, id="hold-not-positive"),
        pytest.param({"baseline_bars": 0}, id="baseline-not-positive"),
        pytest.param({"cooldown_bars": -1}, id="cooldown-negative"),
        pytest.param({"target_weight": 0.0}, id="weight-not-positive"),
        pytest.param({"target_weight": 1.5}, id="weight-above-one"),
    ],
)
def test_invalid_configurations_are_rejected(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        BicConfig(**kwargs)


# ---- checkpointing ---------------------------------------------------


def test_snapshot_roundtrip_preserves_a_held_short() -> None:
    series = _series(E + 40, {E: DOWN})
    context = Context(series)
    strategy = BicMajors()
    for index in range(E + 3):
        context.seek(index)
        strategy.on_bar(context)
    assert strategy.snapshot_state()["side"] == -1.0

    restored = BicMajors()
    restored.restore_state(strategy.snapshot_state())
    assert restored.snapshot_state() == strategy.snapshot_state()

    for index in range(E + 3, len(series)):
        context.seek(index)
        expected = strategy.on_bar(context).target
        assert restored.on_bar(context).target == expected


def test_checkpoint_with_a_position_phase_but_no_side_is_rejected() -> None:
    strategy = BicMajors()
    state = strategy.snapshot_state()
    state["phase"] = "holding"
    state["side"] = 0.0
    state["entry_index"] = 5
    with pytest.raises(ValueError, match="no side"):
        BicMajors().restore_state(state)


def test_checkpoint_from_another_instrument_is_rejected() -> None:
    state = BicMajors(inst_id="ETH-USDT-SWAP").snapshot_state()
    with pytest.raises(ValueError, match="instrument does not match"):
        BicMajors(inst_id="BTC-USDT-SWAP").restore_state(state)
