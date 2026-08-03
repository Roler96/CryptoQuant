"""Performance, inference, and frozen verdict gates for CRDR v1."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, cast

import numpy as np
import pandas as pd

from cq.research.crdr.backtest import BacktestResult

HOURS_PER_YEAR = 24 * 365


def _timestamp(value: str) -> pd.Timestamp:
    return cast(pd.Timestamp, pd.Timestamp(value, tz="UTC"))


EVALUATION_START = _timestamp("2021-05-01")
EVALUATION_END = _timestamp("2025-06-01")
SEGMENT_BOUNDARIES = (
    ("2021-05_to_2022", EVALUATION_START, _timestamp("2022-01-01")),
    (
        "2022",
        _timestamp("2022-01-01"),
        _timestamp("2023-01-01"),
    ),
    (
        "2023",
        _timestamp("2023-01-01"),
        _timestamp("2024-01-01"),
    ),
    (
        "2024",
        _timestamp("2024-01-01"),
        _timestamp("2025-01-01"),
    ),
    ("2025_to_June", _timestamp("2025-01-01"), EVALUATION_END),
)


def performance(result: BacktestResult) -> dict[str, float | int]:
    """Compute metrics from the continuous hourly path and closed episodes."""
    hourly = result.hourly_returns.astype(float)
    hours = len(hourly)
    total_return = float(np.prod(1.0 + hourly.to_numpy()) - 1.0) if hours else 0.0
    if hours and total_return > -1.0:
        annual_return = float((1.0 + total_return) ** (HOURS_PER_YEAR / hours) - 1.0)
    else:
        annual_return = -1.0 if total_return <= -1.0 else 0.0

    standard_deviation = float(hourly.std(ddof=1)) if hours > 1 else 0.0
    if standard_deviation > 0 and np.isfinite(standard_deviation):
        annual_sharpe = float(hourly.mean() / standard_deviation * math.sqrt(HOURS_PER_YEAR))
    else:
        annual_sharpe = 0.0

    cumulative = np.concatenate(([1.0], np.cumprod(1.0 + hourly.to_numpy())))
    running_peak = np.maximum.accumulate(cumulative)
    max_drawdown = float(np.min(cumulative / running_peak - 1.0))

    episode_returns = np.array([episode.net_return for episode in result.episodes], dtype=float)
    long_returns = np.array([episode.long_net_return for episode in result.episodes], dtype=float)
    short_returns = np.array([episode.short_net_return for episode in result.episodes], dtype=float)
    episode_count = len(episode_returns)
    best_episode = float(episode_returns.max()) if episode_count else 0.0
    if episode_count > 1:
        best_position = int(np.argmax(episode_returns))
        less_best = float(np.prod(1.0 + np.delete(episode_returns, best_position)) - 1.0)
    else:
        less_best = 0.0

    return {
        "hours": hours,
        "total_return": total_return,
        "annual_return": annual_return,
        "annual_sharpe": annual_sharpe,
        "max_drawdown": max_drawdown,
        "episode_count": episode_count,
        "mean_episode_return": float(episode_returns.mean()) if episode_count else 0.0,
        "best_episode_return": best_episode,
        "episode_return_less_best": less_best,
        "long_episode_return": float(np.prod(1.0 + long_returns) - 1.0),
        "short_episode_return": float(np.prod(1.0 + short_returns) - 1.0),
    }


def calendar_segments(result: BacktestResult) -> list[dict[str, Any]]:
    """Report the five preregistered calendar slices without regrouping them."""
    segments: list[dict[str, Any]] = []
    for label, start, end in SEGMENT_BOUNDARIES:
        mask = (result.hourly_returns.index >= start) & (result.hourly_returns.index < end)
        hourly = result.hourly_returns.loc[mask]
        equity = (1.0 + hourly).cumprod().rename("equity")
        episodes = tuple(
            episode for episode in result.episodes if start <= episode.entry_time < end
        )
        segment_result = BacktestResult(hourly, equity, episodes)
        segments.append(
            {
                "label": label,
                "start": start.isoformat(),
                "end_exclusive": end.isoformat(),
                "metrics": performance(segment_result),
            }
        )
    return segments


def block_bootstrap(
    hourly_returns: pd.Series,
    *,
    block_days: int = 7,
    samples: int = 5_000,
    seed: int = 0,
) -> dict[str, float | int]:
    """Circular daily block bootstrap for the frozen mean and annual-return tests."""
    if block_days < 1 or samples < 1:
        raise ValueError("block_days and samples must be positive")
    if hourly_returns.empty:
        raise ValueError("bootstrap requires hourly returns")

    daily = (1.0 + hourly_returns).resample("1D").prod() - 1.0
    daily_index = pd.date_range(daily.index[0], daily.index[-1], freq="1D")
    daily = daily.reindex(daily_index, fill_value=0.0)
    values = daily.to_numpy(dtype=float)
    if (values <= -1.0).any():
        raise ValueError("daily return at or below -100% cannot be bootstrapped")

    observed_mean = float(values.mean())
    centered = values - observed_mean
    rng = np.random.default_rng(seed)
    null_means = np.empty(samples, dtype=float)
    annual_returns = np.empty(samples, dtype=float)
    block_offsets = np.arange(block_days)
    blocks_needed = math.ceil(len(values) / block_days)

    for sample in range(samples):
        starts = rng.integers(0, len(values), size=blocks_needed)
        positions = (starts[:, None] + block_offsets[None, :]) % len(values)
        flat_positions = positions.ravel()[: len(values)]
        null_sample = centered[flat_positions]
        raw_sample = values[flat_positions]
        null_means[sample] = float(null_sample.mean())
        annual_returns[sample] = float(
            np.expm1(np.log1p(raw_sample).sum() * 365.0 / len(values))
        )

    p_value = (int(np.count_nonzero(null_means >= observed_mean)) + 1) / (samples + 1)
    return {
        "days": len(values),
        "samples": samples,
        "block_days": block_days,
        "observed_daily_mean": observed_mean,
        "p_value": float(p_value),
        "annual_return_p5": float(np.quantile(annual_returns, 0.05, method="linear")),
    }


def gate_verdict(
    *,
    integrity: bool,
    main: Mapping[str, float | int],
    stress: Mapping[str, float | int],
    segments: list[dict[str, object]],
    neighbors: Mapping[str, Mapping[str, float | int]],
    bootstrap: Mapping[str, float | int],
    ablations: Mapping[str, Mapping[str, float | int]],
) -> dict[str, bool | str | int]:
    """Apply G0-G6 exactly as frozen in the design document."""
    positive_segments = sum(
        _metric(cast(Mapping[str, object], segment["metrics"]), "total_return") > 0
        for segment in segments
    )
    positive_neighbors = sum(_metric(metrics, "total_return") > 0 for metrics in neighbors.values())
    minimum_segment_episodes = min(
        int(_metric(cast(Mapping[str, object], segment["metrics"]), "episode_count"))
        for segment in segments
    )

    gates = {
        "G0": integrity,
        "G1": (
            _metric(main, "total_return") > 0
            and _metric(main, "annual_sharpe") >= 0.75
            and _metric(main, "max_drawdown") >= -0.25
            and _metric(stress, "total_return") > 0
        ),
        "G2": positive_segments >= 4 and positive_neighbors >= 5,
        "G3": (
            _metric(bootstrap, "p_value") <= 0.05
            and _metric(bootstrap, "annual_return_p5") > 0
            and _metric(main, "episode_return_less_best") > 0
        ),
        "G4": (
            _metric(main, "long_episode_return") > 0
            and _metric(main, "short_episode_return") > 0
        ),
        "G5": _metric(main, "episode_count") >= 200 and minimum_segment_episodes >= 20,
        "G6": (
            _metric(main, "annual_sharpe")
            > _metric(ablations["raw_reversal"], "annual_sharpe")
            and _metric(main, "mean_episode_return")
            > _metric(ablations["residual_continuation"], "mean_episode_return")
        ),
    }

    if not gates["G0"]:
        verdict = "INVALID"
    elif _metric(main, "total_return") <= 0 or not gates["G5"]:
        verdict = "CLOSED"
    elif all(gates.values()):
        verdict = "TRADEABLE_LEAD"
    elif all(gates[name] for name in ("G0", "G2", "G3", "G5", "G6")) and (
        not gates["G1"] or not gates["G4"]
    ):
        verdict = "REAL_BUT_SUBTHRESHOLD"
    else:
        verdict = "MECHANISM_UNSUPPORTED"

    return {
        **gates,
        "positive_segments": positive_segments,
        "positive_neighbors": positive_neighbors,
        "minimum_segment_episodes": minimum_segment_episodes,
        "verdict": verdict,
    }


def _metric(metrics: Mapping[str, object], key: str) -> float:
    value = metrics[key]
    if not isinstance(value, (int, float)):
        raise TypeError(f"metric {key} is not numeric")
    return float(value)
