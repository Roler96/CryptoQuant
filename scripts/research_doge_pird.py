"""Open DOGE 5m development scan for PIRD v2."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

from cq.research.propagator_residual import fit_residual_model, propagator_features
from scripts.research_doge_intraday_frontier import load_bars

ROUND_TRIP_COST = 0.003
TARGET_WEIGHT = 0.25


@dataclass(frozen=True)
class PirdTrial:
    side: str
    regression_window: int
    tau: int
    z_resid: float
    hold_bars: int
    episodes: int
    long_episodes: int
    short_episodes: int
    mean_net_bps_on_notional: float
    total_return: float
    sharpe: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    positive_years: int
    active_years: int
    year_returns: dict[str, float]
    long_pnl: float
    short_pnl: float


def _base_features(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    close = frame.close.to_numpy(dtype=float)
    high = frame.high.to_numpy(dtype=float)
    low = frame.low.to_numpy(dtype=float)
    volume = frame.volume.to_numpy(dtype=float)
    returns = np.r_[np.nan, np.diff(np.log(close))]
    dvol = close * volume
    baseline = (
        pd.Series(dvol, index=frame.index)
        .shift(1)
        .rolling(288, min_periods=288)
        .median()
        .to_numpy(dtype=float)
    )
    valid = (
        np.isfinite(returns)
        & np.isfinite(baseline)
        & (baseline > 0.0)
        & (volume > 0.0)
        & (high > low)
    )
    clv = np.zeros(len(frame), dtype=float)
    clv[valid] = 2.0 * (close[valid] - low[valid]) / (high[valid] - low[valid]) - 1.0
    activity = np.full(len(frame), np.nan, dtype=float)
    activity[valid] = dvol[valid] / baseline[valid]
    flow = np.full(len(frame), np.nan, dtype=float)
    flow[valid] = clv[valid] * np.log1p(activity[valid])
    return {
        "returns": returns,
        "activity": activity,
        "flow": flow,
        "clv": clv,
        "valid": valid,
    }


def _daily_frozen_models(
    index: pd.DatetimeIndex,
    change: np.ndarray,
    returns: np.ndarray,
    regression_window: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    alpha = np.full(len(index), np.nan, dtype=float)
    beta = np.full(len(index), np.nan, dtype=float)
    sigma = np.full(len(index), np.nan, dtype=float)
    day_starts = np.flatnonzero((index.hour == 0) & (index.minute == 0))
    boundaries = np.r_[day_starts, len(index)]
    for position, start in enumerate(day_starts):
        stop = int(boundaries[position + 1])
        lower = int(start) - regression_window
        if lower < 0:
            continue
        model = fit_residual_model(change[lower:start], returns[lower:start])
        if model is None:
            continue
        alpha[start:stop] = model.alpha
        beta[start:stop] = model.beta
        sigma[start:stop] = model.sigma
    return alpha, beta, sigma


def _daily_robust_location_scale(
    index: pd.DatetimeIndex,
    values: np.ndarray,
    window: int,
) -> tuple[np.ndarray, np.ndarray]:
    location = np.full(len(index), np.nan, dtype=float)
    scale = np.full(len(index), np.nan, dtype=float)
    day_starts = np.flatnonzero((index.hour == 0) & (index.minute == 0))
    boundaries = np.r_[day_starts, len(index)]
    for position, start in enumerate(day_starts):
        stop = int(boundaries[position + 1])
        lower = int(start) - window
        if lower < 0:
            continue
        sample = values[lower:start]
        if not np.isfinite(sample).all():
            continue
        center = float(np.median(sample))
        mad = float(1.4826 * np.median(np.abs(sample - center)))
        if mad <= 0.0 or not math.isfinite(mad):
            continue
        location[start:stop] = center
        scale[start:stop] = mad
    return location, scale


def _signal(
    returns: np.ndarray,
    change: np.ndarray,
    activity: np.ndarray,
    alpha: np.ndarray,
    beta: np.ndarray,
    sigma: np.ndarray,
    z_resid: float,
) -> np.ndarray:
    predicted = alpha + beta * change
    residual = returns - predicted
    predicted_share = np.full(len(returns), np.nan, dtype=float)
    np.divide(
        np.abs(predicted),
        np.abs(returns),
        out=predicted_share,
        where=np.abs(returns) > 0.0,
    )
    signal = np.zeros(len(returns), dtype=float)
    valid = (
        np.isfinite(predicted)
        & np.isfinite(residual)
        & np.isfinite(sigma)
        & (sigma > 0.0)
        & (beta > 0.0)
        & (activity >= 1.0)
        & (np.abs(residual) / sigma >= z_resid)
        & (np.sign(predicted) == np.sign(residual))
        & (np.sign(residual) == np.sign(returns))
        & (returns != 0.0)
        & (predicted_share >= 0.25)
    )
    signal[valid] = -np.sign(residual[valid])
    return signal


def _evaluate(
    frame: pd.DataFrame,
    signal: np.ndarray,
    *,
    regression_window: int,
    tau: int,
    z_resid: float,
    hold_bars: int,
    side: str = "both",
    round_trip_cost: float = ROUND_TRIP_COST,
) -> PirdTrial:
    opens = frame.open.to_numpy(dtype=float)
    entries: list[int] = []
    decision = regression_window
    last_decision = len(frame) - hold_bars - 2
    while decision <= last_decision:
        if signal[decision] != 0.0:
            entries.append(decision)
            decision += hold_bars + 1
        else:
            decision += 1
    positions = np.asarray(entries, dtype=int)
    if len(positions):
        directions = signal[positions]
        gross = directions * (
            opens[positions + 1 + hold_bars] / opens[positions + 1] - 1.0
        )
        episode_net = gross - round_trip_cost
        portfolio_net = TARGET_WEIGHT * episode_net
        entry_times = pd.DatetimeIndex(frame.index[positions + 1])
    else:
        directions = np.empty(0)
        episode_net = np.empty(0)
        portfolio_net = np.empty(0)
        entry_times = pd.DatetimeIndex([])

    pnl_by_bar = np.zeros(len(frame), dtype=float)
    if len(positions):
        pnl_by_bar[positions + 1 + hold_bars] = portfolio_net
    equity = np.cumprod(1.0 + pnl_by_bar)
    peaks = np.maximum.accumulate(np.r_[1.0, equity])
    max_drawdown = float(np.min(np.r_[1.0, equity] / peaks - 1.0))
    daily = (1.0 + pd.Series(pnl_by_bar, index=frame.index)).resample("1D").prod() - 1.0
    deviation = float(daily.std(ddof=1))
    sharpe = float(daily.mean() / deviation * math.sqrt(365.0)) if deviation > 0.0 else 0.0
    year_returns = {}
    for year in sorted(set(frame.index.year)):
        mask = entry_times.year == year
        if bool(np.any(mask)):
            year_returns[str(year)] = float(np.prod(1.0 + portfolio_net[mask]) - 1.0)
    positive = portfolio_net[portfolio_net > 0.0]
    negative = portfolio_net[portfolio_net < 0.0]
    profit_factor = float(positive.sum() / abs(negative.sum())) if len(negative) else 0.0
    long = directions > 0.0
    short = directions < 0.0
    return PirdTrial(
        side=side,
        regression_window=regression_window,
        tau=tau,
        z_resid=z_resid,
        hold_bars=hold_bars,
        episodes=len(positions),
        long_episodes=int(long.sum()),
        short_episodes=int(short.sum()),
        mean_net_bps_on_notional=(
            float(episode_net.mean() * 10_000.0) if len(episode_net) else 0.0
        ),
        total_return=float(equity[-1] - 1.0),
        sharpe=sharpe,
        max_drawdown=max_drawdown,
        win_rate=float(np.mean(episode_net > 0.0)) if len(episode_net) else 0.0,
        profit_factor=profit_factor,
        positive_years=sum(value > 0.0 for value in year_returns.values()),
        active_years=len(year_returns),
        year_returns=year_returns,
        long_pnl=float(portfolio_net[long].sum()),
        short_pnl=float(portfolio_net[short].sum()),
    )


def run(db_path: Path) -> dict:
    frame = load_bars(db_path)
    base = _base_features(frame)
    signals: dict[tuple[int, int, float], np.ndarray] = {}
    model_components: dict[
        tuple[int, int],
        tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
    ] = {}
    structure_trials = []
    threshold_trials = []
    for tau, regression_window in product((3, 6, 12), (2016, 4032)):
        _state, change = propagator_features(
            base["flow"],
            base["valid"],
            tau=tau,
        )
        alpha, beta, sigma = _daily_frozen_models(
            pd.DatetimeIndex(frame.index),
            change,
            base["returns"],
            regression_window,
        )
        model_components[(tau, regression_window)] = (change, alpha, beta, sigma)
        for z_resid in (3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0):
            signal = _signal(
                base["returns"],
                change,
                base["activity"],
                alpha,
                beta,
                sigma,
                z_resid,
            )
            signals[(tau, regression_window, z_resid)] = signal
            trial = _evaluate(
                frame,
                signal,
                regression_window=regression_window,
                tau=tau,
                z_resid=z_resid,
                hold_bars=12,
            )
            if z_resid <= 4.0:
                structure_trials.append(trial)
            else:
                threshold_trials.append(trial)
    # Open-development branch: every structure had positive gross expectancy but
    # failed after costs at H=12. Preserve that result and inspect whether the
    # residual-decay horizon is simply shorter or longer; this is not confirmation.
    adaptive_trials = []
    if any(trial.mean_net_bps_on_notional + 30.0 > 0.0 for trial in structure_trials):
        for (tau, regression_window, z_resid), signal in signals.items():
            if z_resid > 4.0:
                continue
            for hold_bars in (6, 24):
                adaptive_trials.append(
                    _evaluate(
                        frame,
                        signal,
                        regression_window=regression_window,
                        tau=tau,
                        z_resid=z_resid,
                        hold_bars=hold_bars,
                    )
                )
    # The two-sided candidate fails its direction gate, but the downside-residual
    # long side strengthens monotonically at high z. Treat it as a new adaptive
    # lineage and map its local threshold/tau/hold response surface explicitly.
    long_only_trials = []
    for (tau, regression_window, z_resid), signal in signals.items():
        if tau not in (6, 12) or z_resid < 8.0:
            continue
        long_signal = np.where(signal > 0.0, signal, 0.0)
        for hold_bars in (6, 12, 24):
            long_only_trials.append(
                _evaluate(
                    frame,
                    long_signal,
                    regression_window=regression_window,
                    tau=tau,
                    z_resid=z_resid,
                    hold_bars=hold_bars,
                    side="long_only",
                )
            )
    trials = [
        *structure_trials,
        *threshold_trials,
        *adaptive_trials,
        *long_only_trials,
    ]
    selected_signal = np.where(signals[(12, 4032, 9.0)] > 0.0, 1.0, 0.0)
    selected_costs = {}
    for per_side_bps in (15.0, 20.0, 25.0):
        selected_costs[f"{per_side_bps:g}bps_per_side"] = asdict(
            _evaluate(
                frame,
                selected_signal,
                regression_window=4032,
                tau=12,
                z_resid=9.0,
                hold_bars=12,
                side="long_only",
                round_trip_cost=2.0 * per_side_bps / 10_000.0,
            )
        )

    selected_change, selected_alpha, selected_beta, selected_sigma = model_components[
        (12, 4032)
    ]
    no_activity_raw = _signal(
        base["returns"],
        selected_change,
        np.ones(len(frame), dtype=float),
        selected_alpha,
        selected_beta,
        selected_sigma,
        9.0,
    )
    no_memory_change = np.where(base["valid"], base["flow"], np.nan)
    nm_alpha, nm_beta, nm_sigma = _daily_frozen_models(
        pd.DatetimeIndex(frame.index),
        no_memory_change,
        base["returns"],
        4032,
    )
    no_memory_raw = _signal(
        base["returns"],
        no_memory_change,
        base["activity"],
        nm_alpha,
        nm_beta,
        nm_sigma,
        9.0,
    )
    _clv_state, clv_change = propagator_features(
        base["clv"],
        base["valid"],
        tau=12,
    )
    clv_alpha, clv_beta, clv_sigma = _daily_frozen_models(
        pd.DatetimeIndex(frame.index),
        clv_change,
        base["returns"],
        4032,
    )
    clv_raw = _signal(
        base["returns"],
        clv_change,
        base["activity"],
        clv_alpha,
        clv_beta,
        clv_sigma,
        9.0,
    )
    raw_location, raw_scale = _daily_robust_location_scale(
        pd.DatetimeIndex(frame.index),
        base["returns"],
        4032,
    )
    raw_return_z = (base["returns"] - raw_location) / raw_scale
    raw_return_signal = np.where(
        (raw_return_z <= -9.0) & (base["activity"] >= 1.0),
        1.0,
        0.0,
    )
    ablation_signals = {
        "same_events_continuation": -selected_signal,
        "raw_return_reversal": raw_return_signal,
        "no_activity_gate": np.where(no_activity_raw > 0.0, 1.0, 0.0),
        "no_memory_flow": np.where(no_memory_raw > 0.0, 1.0, 0.0),
        "clv_only_flow": np.where(clv_raw > 0.0, 1.0, 0.0),
    }
    ablations = {
        name: asdict(
            _evaluate(
                frame,
                signal,
                regression_window=4032,
                tau=12,
                z_resid=9.0,
                hold_bars=12,
                side=name,
            )
        )
        for name, signal in ablation_signals.items()
    }
    ranked = sorted(
        trials,
        key=lambda trial: (
            trial.positive_years,
            trial.sharpe,
            trial.mean_net_bps_on_notional,
        ),
        reverse=True,
    )
    return {
        "study": "doge-pird-v2-open-development",
        "mode": "adaptive_open_development_on_seen_history_not_confirmation",
        "executed_at": datetime.now(UTC).isoformat(),
        "data": {
            "start": frame.index[0].isoformat(),
            "end_inclusive": frame.index[-1].isoformat(),
            "bars": len(frame),
            "untouched_holdout": False,
        },
        "execution": {
            "entry": "signal close then next 5m open",
            "exit": "fixed future 5m open",
            "target_weight": TARGET_WEIGHT,
            "cost_bps_per_side": 15.0,
        },
        "search": {
            "stage": "structure_plus_adaptive_horizon_diagnostic",
            "trial_count": len(trials),
            "structure_trials": len(structure_trials),
            "adaptive_threshold_trials": len(threshold_trials),
            "adaptive_trials": len(adaptive_trials),
            "adaptive_long_only_trials": len(long_only_trials),
            "hold_bars": [6, 12, 24],
            "adaptive_reason": (
                "all H=12 structures had positive gross expectancy but failed "
                "after costs; inspect residual strength/horizon, then map the "
                "result-driven downside-residual long-only lineage without "
                "claiming OOS"
            ),
        },
        "selected_development_candidate": {
            "lineage": "two_sided_pird_v2 -> downside_residual_long_only",
            "selection": "W=4032,tau=12,z=9,H=12 local plateau center",
            "cost_sensitivity": selected_costs,
            "ablations": ablations,
        },
        "top_10": [asdict(trial) for trial in ranked[:10]],
        "trials": [asdict(trial) for trial in trials],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("data/cq.db"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/research/doge_pird_v2_open_development.json"),
    )
    args = parser.parse_args()
    report = run(args.db)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"search": report["search"], "top_10": report["top_10"]}, indent=2))


if __name__ == "__main__":
    main()
