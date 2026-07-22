from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from cq.context import Context, Series
from cq.core.types import CostModel
from research.audit_doge_vcse_robustness import (
    _block_bootstrap,
    _matched_random_null,
    _phase_series,
    _round_trip_factors,
    _year_jackknife,
)
from research.backtest_doge_vcse import DogeVcse, VcseParams, _atr_state
from research.explore_doge_vcse_v2 import _v2_params
from research.report_doge_vcse_yearly import WindowedVcse

HOUR4_MS = 4 * 60 * 60 * 1000


def _series(seed: int = 7, bars: int = 800) -> Series:
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0002, 0.025, bars)
    close = 100 * np.exp(np.cumsum(returns))
    spread = rng.uniform(0.002, 0.03, bars) * close
    high = np.maximum(close, np.r_[close[0], close[:-1]]) + spread
    low = np.minimum(close, np.r_[close[0], close[:-1]]) - spread
    return Series(
        "DOGE-USDT",
        "4h",
        np.arange(bars, dtype=np.int64) * HOUR4_MS,
        np.r_[close[0], close[:-1]],
        high,
        low,
        close,
        rng.lognormal(14, 0.8, bars),
    )


def _targets(series: Series) -> list[float]:
    strategy = DogeVcse()
    ctx = Context(series)
    out: list[float] = []
    for index in range(len(series)):
        ctx.seek(index)
        if index + 1 < strategy.warmup_bars:
            out.append(0.0)
        else:
            out.append(strategy.on_bar(ctx).target)
    return out


def test_atr_state_matches_hand_calculation() -> None:
    close = np.array([10.0, 11.0, 10.0, 12.0, 13.0])
    high = close + 1.0
    low = close - 1.0
    atr, atr_pct, tr = _atr_state(high, low, close, bars=2)

    assert np.isnan(tr[0])
    np.testing.assert_allclose(tr[1:], [2.0, 2.0, 3.0, 2.0])
    np.testing.assert_allclose(atr[2:], [2.0, 2.5, 2.5])
    np.testing.assert_allclose(atr_pct[2:], atr[2:] / close[2:])


def test_signal_is_prefix_invariant() -> None:
    original = _series()
    cutoff = 700
    changed_close = np.array(original.close)
    changed_high = np.array(original.high)
    changed_low = np.array(original.low)
    changed_volume = np.array(original.volume)
    changed_close[cutoff + 1 :] *= 4.0
    changed_high[cutoff + 1 :] *= 4.0
    changed_low[cutoff + 1 :] *= 4.0
    changed_volume[cutoff + 1 :] *= 100.0
    changed = Series(
        original.inst_id,
        original.timeframe,
        original.ts,
        original.open,
        changed_high,
        changed_low,
        changed_close,
        changed_volume,
    )

    assert _targets(original)[: cutoff + 1] == _targets(changed)[: cutoff + 1]


def test_strategy_never_targets_short() -> None:
    targets = _targets(_series(seed=11))
    assert set(targets).issubset({0.0, 1.0})


def test_reset_clears_carried_state() -> None:
    strategy = DogeVcse()
    strategy._target = 1.0
    strategy._entry_index = 100
    strategy._peak_close = 50.0

    strategy.reset()

    assert strategy._target == 0.0
    assert strategy._entry_index is None
    assert strategy._peak_close == 0.0


def test_invalid_parameters_fail_fast() -> None:
    with pytest.raises(ValueError):
        VcseParams(compression_quantile=1.0)
    with pytest.raises(ValueError):
        VcseParams(breakout_bars=1)
    with pytest.raises(ValueError):
        VcseParams(volume_multiplier=0.0)


def test_windowed_strategy_stays_flat_before_start() -> None:
    series = _series()
    strategy = WindowedVcse(
        start_ms=int(series.ts[700] + HOUR4_MS),
        end_ms=None,
    )
    ctx = Context(series)
    ctx.seek(699)

    assert strategy.on_bar(ctx).target == 0.0


def test_windowed_strategy_forces_flat_at_end() -> None:
    series = _series()
    strategy = WindowedVcse(
        start_ms=0,
        end_ms=int(series.ts[700] + HOUR4_MS),
    )
    strategy.inner._target = 1.0
    ctx = Context(series)
    ctx.seek(700)

    assert strategy.on_bar(ctx).target == 0.0


def test_phase_series_keeps_only_complete_shifted_groups() -> None:
    index = pd.date_range("2026-01-01", periods=9, freq="1h", tz="UTC")
    frame = pd.DataFrame(
        {
            "open": np.arange(9, dtype=float) + 1,
            "high": np.arange(9, dtype=float) + 2,
            "low": np.arange(9, dtype=float),
            "close": np.arange(9, dtype=float) + 1.5,
            "volume": np.ones(9),
        },
        index=index,
    ).iloc[[0, 1, 3, 4, 5, 6, 7, 8]]

    phase = _phase_series(frame, 0)

    assert len(phase) == 1
    assert phase.open[0] == 5.0
    assert phase.high[0] == 9.0
    assert phase.low[0] == 4.0
    assert phase.close[0] == 8.5
    assert phase.volume[0] == 4.0


def test_block_bootstrap_is_reproducible_and_preserves_positive_paths() -> None:
    first = _block_bootstrap([0.01, 0.02, 0.03], 2, samples=100, seed=3)
    second = _block_bootstrap([0.01, 0.02, 0.03], 2, samples=100, seed=3)

    assert first == second
    assert first["p05"] > 0
    assert first["probability_of_loss"] == 0


def test_year_jackknife_removes_all_episodes_from_each_year() -> None:
    rows = _year_jackknife([0.10, -0.05, 0.20], [2024, 2024, 2025])

    assert rows == [
        {
            "removed_year": 2024,
            "removed_trades": 2,
            "remaining_trades": 1,
            "return": pytest.approx(0.20),
        },
        {
            "removed_year": 2025,
            "removed_trades": 1,
            "remaining_trades": 2,
            "return": pytest.approx(0.045),
        },
    ]


def test_round_trip_factor_charges_both_sides() -> None:
    entry = np.array([100.0])
    exit_ = np.array([110.0])

    free = _round_trip_factors(
        entry, exit_, CostModel(fee_bps=0.0, slippage_bps=0.0)
    )
    charged = _round_trip_factors(
        entry, exit_, CostModel(fee_bps=10.0, slippage_bps=5.0)
    )

    assert free[0] == pytest.approx(1.1)
    assert charged[0] < free[0]


def test_matched_random_null_matches_year_and_holding_period() -> None:
    series = _series(bars=12)
    spans: list[tuple[int, int | None]] = [
        (int(series.ts[2]), int(series.ts[5]))
    ]

    result = _matched_random_null(
        series,
        spans,
        observed=0.0,
        samples=50,
        seed=4,
        family_trials=2,
        costs=CostModel(),
    )

    assert result["trades_matched"] == 1
    assert result["samples"] == 50
    assert 0 <= result["p_value"] <= 1
    assert result["family_adjusted_p"] >= result["p_value"]


def test_v2_only_removes_clv_and_volume_confirmations() -> None:
    v1 = VcseParams()
    v2 = _v2_params()

    assert v2.use_clv is False
    assert v2.use_volume is False
    assert replace(v2, use_clv=True, use_volume=True) == v1
