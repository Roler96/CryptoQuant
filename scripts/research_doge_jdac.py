"""Open development scan for DOGE jump-diffusion confirmation (JDAC)."""

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

from scripts.research_doge_intraday_frontier import load_bars

ROUND_TRIP_COST = 0.003
TARGET_WEIGHT = 0.25


@dataclass(frozen=True)
class JdacTrial:
    diffusion_window: int
    jump_z: float
    confirm_bars: int
    retention: float
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


def jdac_signal(
    frame: pd.DataFrame,
    *,
    diffusion_window: int,
    jump_z: float,
    confirm_bars: int,
    retention: float,
    use_bipower: bool = True,
) -> pd.Series:
    log_close = np.log(frame.close.astype(float))
    returns = log_close.diff()
    abs_returns = returns.abs()
    if use_bipower:
        products = abs_returns * abs_returns.shift(1)
        scale = np.sqrt(
            math.pi
            / 2.0
            * products.shift(1).rolling(
                diffusion_window - 1,
                min_periods=diffusion_window - 1,
            ).mean()
        )
    else:
        scale = returns.shift(1).rolling(
            diffusion_window,
            min_periods=diffusion_window,
        ).std(ddof=1)
    jump_score = abs_returns / scale.replace(0.0, np.nan)
    log_range = np.log(frame.high.astype(float) / frame.low.astype(float))
    body_ratio = abs_returns / log_range.replace(0.0, np.nan)
    dvol = frame.close.astype(float) * frame.volume.astype(float)
    baseline_dvol = dvol.shift(1).rolling(
        diffusion_window,
        min_periods=diffusion_window,
    ).median()
    jump = (
        (jump_score >= jump_z)
        & (body_ratio >= 0.60)
        & (dvol / baseline_dvol.replace(0.0, np.nan) >= 2.0)
        & (frame.volume > 0.0)
        & (frame.high > frame.low)
    )

    direction = np.sign(returns.shift(confirm_bars))
    jump_size = abs_returns.shift(confirm_bars)
    retained_move = direction * (log_close - log_close.shift(confirm_bars + 1))
    retained_fraction = retained_move / jump_size.replace(0.0, np.nan)
    post_noise = np.sqrt(
        returns.pow(2).rolling(confirm_bars, min_periods=confirm_bars).sum()
    )
    post_move = direction * (log_close - log_close.shift(confirm_bars))
    confirmed = (
        jump.shift(confirm_bars, fill_value=False)
        & (retained_fraction >= retention)
        & (post_move >= -0.5 * post_noise)
    )
    return pd.Series(direction, index=frame.index).where(confirmed, 0.0).fillna(0.0)


def evaluate(
    frame: pd.DataFrame,
    signal: pd.Series,
    *,
    diffusion_window: int,
    jump_z: float,
    confirm_bars: int,
    retention: float,
    hold_bars: int,
) -> JdacTrial:
    values = signal.to_numpy(dtype=float)
    opens = frame.open.to_numpy(dtype=float)
    entries: list[int] = []
    decision = diffusion_window + confirm_bars + 1
    last_decision = len(frame) - hold_bars - 2
    while decision <= last_decision:
        if values[decision] != 0.0:
            entries.append(decision)
            decision += hold_bars + 1
        else:
            decision += 1
    positions = np.asarray(entries, dtype=int)
    if len(positions):
        directions = values[positions]
        gross = directions * (
            opens[positions + 1 + hold_bars] / opens[positions + 1] - 1.0
        )
        episode_net = gross - ROUND_TRIP_COST
        portfolio_net = TARGET_WEIGHT * episode_net
        entry_times = frame.index[positions + 1]
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
    return JdacTrial(
        diffusion_window=diffusion_window,
        jump_z=jump_z,
        confirm_bars=confirm_bars,
        retention=retention,
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
    trials = []
    for n, z, d, rho in product((144, 288), (4.0, 5.0, 6.0), (2, 3), (0.60, 0.80)):
        signal = jdac_signal(
            frame,
            diffusion_window=n,
            jump_z=z,
            confirm_bars=d,
            retention=rho,
        )
        trials.append(
            evaluate(
                frame,
                signal,
                diffusion_window=n,
                jump_z=z,
                confirm_bars=d,
                retention=rho,
                hold_bars=24,
            )
        )
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
        "study": "doge-jdac-open-development-v1",
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
        "search": {"stage": "structure", "trial_count": len(trials), "hold_bars": 24},
        "top_10": [asdict(trial) for trial in ranked[:10]],
        "trials": [asdict(trial) for trial in trials],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("data/cq.db"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/research/doge_jdac_open_development_v1.json"),
    )
    args = parser.parse_args()
    report = run(args.db)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"search": report["search"], "top_10": report["top_10"]}, indent=2))


if __name__ == "__main__":
    main()
