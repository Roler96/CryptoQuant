from __future__ import annotations

import numpy as np
import pytest

from cq.context import Context, Series
from cq.research.split import to_ms
from research.explore_doge_volatility_managed_spot import (
    DogeVolatilityManagedSpot,
    VmsParams,
)

DAY_MS = 24 * 60 * 60 * 1000
START = to_ms("2021-01-04")


def _series_from_logrets(logrets: list[float], base: float = 100.0) -> Series:
    close = base * np.exp(np.concatenate([[0.0], np.cumsum(np.asarray(logrets))]))
    n = len(close)
    return Series(
        inst_id="DOGE-USDT",
        timeframe="1d",
        ts=START + np.arange(n, dtype=np.int64) * DAY_MS,
        open=close,
        high=close * 1.001,
        low=close * 0.999,
        close=close,
        volume=np.full(n, 100.0),
    )


def _params(**overrides: object) -> VmsParams:
    values: dict[str, object] = {"rv_window": 2, "median_window": 4}
    values.update(overrides)
    return VmsParams(**values)  # type: ignore[arg-type]


def _final_target(strategy: DogeVolatilityManagedSpot, series: Series) -> float:
    ctx = Context(series)
    ctx.seek(len(series) - 1)
    return strategy.on_bar(ctx).target


# Six log returns -> seven closes -> exactly the 2+4+1 warmup of _params().
_CALM = [0.01, -0.01, 0.01, -0.01, 0.01, -0.01]
_SPIKE = [0.01, -0.01, 0.01, -0.01, 0.30, -0.30]


def test_uniform_volatility_is_held_at_full_weight() -> None:
    series = _series_from_logrets(_CALM)
    assert _final_target(DogeVolatilityManagedSpot(_params()), series) == 1.0


def test_volatility_spike_scales_the_position_down() -> None:
    series = _series_from_logrets(_SPIKE)
    target = _final_target(DogeVolatilityManagedSpot(_params()), series)
    assert 0.0 < target < 1.0
    # Weight is quantised to the nearest 5%.
    assert target == pytest.approx(round(target / 0.05) * 0.05)


def test_anti_direction_adds_weight_where_inverse_removes_it() -> None:
    series = _series_from_logrets(_SPIKE)
    inverse = _final_target(DogeVolatilityManagedSpot(_params()), series)
    anti = _final_target(
        DogeVolatilityManagedSpot(_params(direction="anti")), series
    )
    assert anti > inverse


def test_weight_is_scale_invariant_in_price_level() -> None:
    cheap = _series_from_logrets(_SPIKE, base=1.0)
    dear = _series_from_logrets(_SPIKE, base=5000.0)
    assert _final_target(
        DogeVolatilityManagedSpot(_params()), cheap
    ) == _final_target(DogeVolatilityManagedSpot(_params()), dear)


def test_weight_never_leaves_the_spot_range() -> None:
    series = _series_from_logrets(_SPIKE)
    strategy = DogeVolatilityManagedSpot(_params())
    ctx = Context(series)
    for index in range(strategy.warmup_bars - 1, len(series)):
        ctx.seek(index)
        assert 0.0 <= strategy.on_bar(ctx).target <= 1.0


def test_signal_is_prefix_invariant_to_future_bars() -> None:
    short = _series_from_logrets(_SPIKE)
    extended = _series_from_logrets([*_SPIKE, 0.05, -0.2, 0.1, 0.0])
    short_ctx = Context(short)
    long_ctx = Context(extended)
    decision = len(short) - 1
    short_ctx.seek(decision)
    long_ctx.seek(decision)

    assert DogeVolatilityManagedSpot(_params()).on_bar(short_ctx) == (
        DogeVolatilityManagedSpot(_params()).on_bar(long_ctx)
    )


def test_warmup_bars_and_default_name() -> None:
    strategy = DogeVolatilityManagedSpot()
    assert strategy.warmup_bars == 20 + 180 + 1
    assert strategy.name == "doge-vms-inverse-20-180d"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("rv_window", 1),
        ("median_window", 1),
        ("size_cap", 0.0),
        ("size_cap", 1.5),
        ("quantize", 0.0),
        ("quantize", 2.0),
        ("direction", "sideways"),
    ],
)
def test_parameter_validation(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        _params(**{field: value})
