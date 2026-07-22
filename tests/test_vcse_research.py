from __future__ import annotations

import numpy as np
import pytest

from cq.context import Context, Series
from research.backtest_doge_vcse import DogeVcse, VcseParams, _atr_state
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
