"""Causal and engine-parity tests for coherent-path exhaustion research."""

from __future__ import annotations

import numpy as np
import pytest

from cq.context import Context, Series
from cq.core.types import CostModel, MarketSpec, Sizing
from cq.engine.loop import run_backtest
from cq.research.coherent_path import CoherentPathConfig, CoherentPathStrategy, signal_target

BAR_MS = 900_000


def _series(closes: list[float], *, future_open_shift: float = 0.0) -> Series:
    values = np.asarray(closes, dtype=float)
    opens = values.copy()
    if future_open_shift:
        opens[19:] += future_open_shift
    return Series(
        "DOGE-USDT-SWAP",
        "15m",
        np.arange(len(values), dtype=np.int64) * BAR_MS,
        opens,
        np.maximum(opens, values),
        np.minimum(opens, values),
        values,
        np.full(len(values), 1_000.0),
    )


def test_signal_reverses_a_coherent_path_and_rejects_chop() -> None:
    config = CoherentPathConfig(window_bars=18, efficiency_threshold=0.78)
    coherent = np.exp(np.linspace(0.0, 0.18, 19))
    choppy = np.asarray([100.0, 101.0] * 9 + [100.5])

    volume = np.ones(19)
    assert signal_target(coherent, volume, config) == -1.0
    assert signal_target(coherent[::-1], volume, config) == 1.0
    assert signal_target(choppy, volume, config) == 0.0


def test_signal_rejects_a_zero_volume_path() -> None:
    closes = np.exp(np.linspace(0.0, 0.18, 19))
    volume = np.ones(19)
    volume[5] = 0.0

    assert signal_target(closes, volume, CoherentPathConfig()) == 0.0


def test_decision_is_invariant_to_future_open_prices() -> None:
    closes = np.exp(np.linspace(0.0, 0.40, 40)).tolist()
    first = _series(closes)
    second = _series(closes, future_open_shift=99.0)

    targets = []
    for series in (first, second):
        context = Context(series)
        context.seek(18)
        targets.append(CoherentPathStrategy().on_bar(context).target)

    assert targets == [-0.25, -0.25]


def test_fixed_hold_exits_at_the_preregistered_future_open() -> None:
    series = _series(np.exp(np.linspace(0.0, 0.80, 80)).tolist())
    strategy = CoherentPathStrategy(
        CoherentPathConfig(window_bars=18, efficiency_threshold=0.78, hold_bars=12)
    )
    context = Context(series)
    targets = []
    for index in range(18, 32):
        context.seek(index)
        targets.append(strategy.on_bar(context).target)

    assert targets[0] == -0.25  # decision 18 -> entry open 19
    assert targets[1:12] == [-0.25] * 11
    assert targets[12] == 0.0  # decision 30 -> exit open 31
    assert targets[13] == -0.25  # earliest next decision 31 -> entry open 32


def test_shared_engine_uses_next_open_and_exact_hold() -> None:
    series = _series(np.exp(np.linspace(0.0, 0.80, 80)).tolist())
    result = run_backtest(
        CoherentPathStrategy(
            CoherentPathConfig(
                window_bars=18,
                efficiency_threshold=0.78,
                hold_bars=12,
                evaluation_end_ms=len(series) * BAR_MS,
            )
        ),
        series,
        MarketSpec(
            "DOGE-USDT-SWAP",
            "swap",
            lot_size=0.0,
            min_notional=0.0,
            max_leverage=1.0,
            maintenance_margin_rate=0.0,
            contract_size=1.0,
        ),
        costs=CostModel(fee_bps=0.0, slippage_bps=0.0),
        sizing=Sizing.ON_ENTRY,
        dust_fraction=0.0,
    )

    fill_times = [fill.ts for fill in result.fills]
    assert fill_times[:4] == [19 * BAR_MS, 31 * BAR_MS, 32 * BAR_MS, 44 * BAR_MS]
    assert result.rejections == []
    assert result.portfolio.is_flat


def test_config_rejects_invalid_parameters() -> None:
    constructors = (
        lambda: CoherentPathConfig(window_bars=1),
        lambda: CoherentPathConfig(efficiency_threshold=0.0),
        lambda: CoherentPathConfig(efficiency_threshold=1.1),
        lambda: CoherentPathConfig(hold_bars=0),
        lambda: CoherentPathConfig(target_weight=0.0),
        lambda: CoherentPathConfig(target_weight=1.1),
    )
    for constructor in constructors:
        with pytest.raises(ValueError):
            constructor()
