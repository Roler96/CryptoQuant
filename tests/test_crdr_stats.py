from __future__ import annotations

from dataclasses import replace
from typing import cast

import numpy as np
import pandas as pd
import pytest

from cq.research.crdr.backtest import BacktestResult, Episode
from cq.research.crdr.stats import (
    block_bootstrap,
    calendar_segments,
    gate_verdict,
    performance,
)


def _result(returns: list[float], *, start: str = "2021-05-01") -> BacktestResult:
    index = pd.date_range(start, periods=len(returns), freq="1h", tz="UTC")
    series = pd.Series(returns, index=index, name="return")
    equity = (1.0 + series).cumprod().rename("equity")
    return BacktestResult(series, equity, ())


def _episode(day: str, net: float, *, long_net: float = 0.001, short_net: float = 0.001) -> Episode:
    checkpoint = cast(pd.Timestamp, pd.Timestamp(day, tz="UTC"))
    entry = cast(pd.Timestamp, checkpoint + pd.Timedelta(hours=1))
    exit_ = cast(pd.Timestamp, checkpoint + pd.Timedelta(hours=7))
    return Episode(
        checkpoint=checkpoint,
        entry_time=entry,
        exit_time=exit_,
        weights=(),
        gross_return=net + 0.003,
        net_return=net,
        long_net_return=long_net,
        short_net_return=short_net,
    )


def test_performance_includes_inactive_hours_and_anchors_drawdown() -> None:
    metrics = performance(_result([0.0, 0.01, 0.0, -0.005]))

    assert metrics["total_return"] == pytest.approx((1.01 * 0.995) - 1.0)
    assert metrics["max_drawdown"] == pytest.approx(-0.005)
    assert metrics["hours"] == 4


def test_performance_reports_episode_concentration_and_both_legs() -> None:
    result = _result([0.0] * 72)
    episodes = (
        _episode("2021-05-01", 0.02, long_net=0.012, short_net=0.008),
        _episode("2021-05-02", 0.01, long_net=0.004, short_net=0.006),
    )

    metrics = performance(replace(result, episodes=episodes))

    assert metrics["episode_count"] == 2
    assert metrics["mean_episode_return"] == pytest.approx(0.015)
    assert metrics["best_episode_return"] == pytest.approx(0.02)
    assert metrics["episode_return_less_best"] == pytest.approx(0.01)
    assert metrics["long_episode_return"] == pytest.approx((1.012 * 1.004) - 1.0)
    assert metrics["short_episode_return"] == pytest.approx((1.008 * 1.006) - 1.0)


def test_bootstrap_is_reproducible_and_positive_path_has_positive_p5() -> None:
    daily = np.tile([0.002, 0.001, 0.003, 0.0], 100)
    hourly = np.repeat(np.power(1.0 + daily, 1 / 24) - 1.0, 24)
    result = _result(hourly.tolist())

    left = block_bootstrap(result.hourly_returns, samples=300, seed=0)
    right = block_bootstrap(result.hourly_returns, samples=300, seed=0)

    assert left == right
    assert 0.0 <= left["p_value"] <= 1.0
    assert left["annual_return_p5"] > 0.0


def test_calendar_segments_use_the_five_frozen_boundaries() -> None:
    index = pd.date_range("2021-05-01", "2025-05-31 23:00", freq="1h", tz="UTC")
    result = _result([0.0] * len(index))

    segments = calendar_segments(result)

    assert [segment["label"] for segment in segments] == [
        "2021-05_to_2022",
        "2022",
        "2023",
        "2024",
        "2025_to_June",
    ]
    assert [segment["metrics"]["hours"] for segment in segments] == [
        245 * 24,
        365 * 24,
        365 * 24,
        366 * 24,
        151 * 24,
    ]


def _passing_metrics() -> dict[str, float | int]:
    return {
        "total_return": 0.20,
        "annual_sharpe": 1.0,
        "max_drawdown": -0.10,
        "episode_count": 250,
        "mean_episode_return": 0.001,
        "episode_return_less_best": 0.15,
        "long_episode_return": 0.10,
        "short_episode_return": 0.08,
    }


def _passing_segments() -> list[dict[str, object]]:
    return [
        {"label": str(index), "metrics": {**_passing_metrics(), "episode_count": 50}}
        for index in range(5)
    ]


def _passing_neighbors() -> dict[str, dict[str, float | int]]:
    return {str(index): _passing_metrics() for index in range(6)}


def _passing_ablations() -> dict[str, dict[str, float | int]]:
    raw = {**_passing_metrics(), "annual_sharpe": 0.8}
    continuation = {**_passing_metrics(), "mean_episode_return": -0.001}
    return {"raw_reversal": raw, "residual_continuation": continuation}


def _passing_bootstrap() -> dict[str, float]:
    return {"p_value": 0.01, "annual_return_p5": 0.05}


def test_all_gates_produce_tradeable_lead() -> None:
    result = gate_verdict(
        integrity=True,
        main=_passing_metrics(),
        stress=_passing_metrics(),
        segments=_passing_segments(),
        neighbors=_passing_neighbors(),
        bootstrap=_passing_bootstrap(),
        ablations=_passing_ablations(),
    )

    assert all(result[f"G{index}"] for index in range(7))
    assert result["verdict"] == "TRADEABLE_LEAD"


def test_positive_result_does_not_promote_when_residualization_adds_nothing() -> None:
    ablations = _passing_ablations()
    ablations["raw_reversal"] = {**_passing_metrics(), "annual_sharpe": 1.2}

    result = gate_verdict(
        integrity=True,
        main=_passing_metrics(),
        stress=_passing_metrics(),
        segments=_passing_segments(),
        neighbors=_passing_neighbors(),
        bootstrap=_passing_bootstrap(),
        ablations=ablations,
    )

    assert result["G6"] is False
    assert result["verdict"] == "MECHANISM_UNSUPPORTED"


@pytest.mark.parametrize(
    ("integrity", "main_return", "stress_return", "expected"),
    [
        (False, 0.20, 0.20, "INVALID"),
        (True, -0.01, 0.20, "CLOSED"),
        (True, 0.20, -0.01, "REAL_BUT_SUBTHRESHOLD"),
    ],
)
def test_verdict_precedence(
    integrity: bool,
    main_return: float,
    stress_return: float,
    expected: str,
) -> None:
    main = {**_passing_metrics(), "total_return": main_return}
    stress = {**_passing_metrics(), "total_return": stress_return}

    result = gate_verdict(
        integrity=integrity,
        main=main,
        stress=stress,
        segments=_passing_segments(),
        neighbors=_passing_neighbors(),
        bootstrap=_passing_bootstrap(),
        ablations=_passing_ablations(),
    )

    assert result["verdict"] == expected


def test_sample_floor_closes_an_otherwise_positive_candidate() -> None:
    main = {**_passing_metrics(), "episode_count": 199}

    result = gate_verdict(
        integrity=True,
        main=main,
        stress=_passing_metrics(),
        segments=_passing_segments(),
        neighbors=_passing_neighbors(),
        bootstrap=_passing_bootstrap(),
        ablations=_passing_ablations(),
    )

    assert result["G5"] is False
    assert result["verdict"] == "CLOSED"
