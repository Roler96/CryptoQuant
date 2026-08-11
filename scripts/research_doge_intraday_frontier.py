"""Second open DOGE-only intraday mechanism frontier.

Adaptive discovery only. The full available 5m history has already been inspected by
prior studies, so annual slices are development diagnostics rather than untouched OOS.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_COST = 0.003
BARS_PER_DAY = 288


@dataclass(frozen=True)
class Candidate:
    family: str
    variant: str
    signal: pd.Series

    @property
    def key(self) -> str:
        return f"{self.family}:{self.variant}"


@dataclass(frozen=True)
class Trial:
    family: str
    variant: str
    orientation: str
    hold_bars: int
    events: int
    mean_net_bps: float
    win_rate: float
    profit_factor: float
    total_return: float
    sharpe: float
    max_drawdown: float
    positive_years: int
    active_years: int
    year_returns: dict[str, float]


def load_bars(db_path: Path) -> pd.DataFrame:
    connection = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    try:
        frame = pd.read_sql_query(
            """SELECT ts, open, high, low, close, volume, quote_volume
               FROM ohlcv
               WHERE inst_id='DOGE-USDT-SWAP' AND timeframe='5m'
               ORDER BY ts""",
            connection,
        )
    finally:
        connection.close()
    if frame.empty:
        raise RuntimeError("DOGE 5m query returned no bars")
    expected = np.arange(frame.ts.iloc[0], frame.ts.iloc[-1] + 300_000, 300_000)
    if len(expected) != len(frame) or not np.array_equal(expected, frame.ts.to_numpy()):
        raise RuntimeError("DOGE 5m bars are not contiguous")
    numeric = frame.drop(columns="ts").to_numpy(dtype=float)
    if not np.isfinite(numeric).all():
        raise RuntimeError("DOGE input contains non-finite values")
    if (frame[["open", "high", "low", "close"]] <= 0.0).any().any():
        raise RuntimeError("DOGE input contains non-positive prices")
    if (frame[["volume", "quote_volume"]] < 0.0).any().any():
        raise RuntimeError("DOGE input contains negative volume")
    frame.index = pd.to_datetime(frame.pop("ts"), unit="ms", utc=True)
    return frame


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator / denominator.replace(0.0, np.nan)


def build_candidate_signals(frame: pd.DataFrame) -> list[Candidate]:
    """Build causal state signals; every rolling reference excludes the current bar."""
    close = frame.close.astype(float)
    returns = np.log(close / close.shift(1))
    abs_returns = returns.abs()
    quote_volume = frame.quote_volume.astype(float)
    valid = (frame.volume > 0.0) & (quote_volume > 0.0)

    trailing_sigma = returns.shift(1).rolling(7 * BARS_PER_DAY, min_periods=BARS_PER_DAY).std()
    return_z = _safe_ratio(abs_returns, trailing_sigma)
    qv_median = quote_volume.shift(1).rolling(
        7 * BARS_PER_DAY, min_periods=BARS_PER_DAY
    ).median()
    qv_ratio = _safe_ratio(quote_volume, qv_median)
    direction = np.sign(returns)
    candidates: list[Candidate] = []

    # Periodic algorithmic participation: surprise activity on a quarter-hour boundary.
    phase = frame.index.hour * 12 + frame.index.minute // 5
    phase_median = quote_volume.groupby(phase).transform(
        lambda values: values.shift(1).rolling(30, min_periods=15).median()
    )
    phase_qv_ratio = _safe_ratio(quote_volume, phase_median)
    quarter_boundary = frame.index.minute % 15 == 0
    for threshold in (1.5, 2.0, 3.0):
        raw = direction.where(
            quarter_boundary & (phase_qv_ratio >= threshold) & (return_z >= 1.0) & valid,
            0.0,
        )
        candidates.append(Candidate("quarter_hour_impulse", f"qv={threshold:g}", raw))

    # Discontinuous return innovations can either propagate or decay after next-open entry.
    for threshold in (3.0, 4.0, 5.0):
        raw = direction.where((return_z >= threshold) & (qv_ratio >= 1.0) & valid, 0.0)
        candidates.append(Candidate("jump_aftershock", f"z={threshold:g}", raw))

    # A low-variance inventory-building state followed by a high-volume directional release.
    squared = returns.pow(2)
    short_variance = squared.shift(1).rolling(12, min_periods=12).mean()
    long_variance = squared.shift(1).rolling(BARS_PER_DAY, min_periods=BARS_PER_DAY).mean()
    compression = np.sqrt(_safe_ratio(short_variance, long_variance))
    for ceiling in (0.45, 0.60, 0.75):
        raw = direction.where(
            (compression <= ceiling) & (return_z >= 1.5) & (qv_ratio >= 1.5) & valid,
            0.0,
        )
        candidates.append(Candidate("compression_release", f"ratio={ceiling:g}", raw))

    # Large movement per traded dollar indicates a transient liquidity vacuum.
    illiquidity = _safe_ratio(abs_returns, quote_volume)
    illiquidity_median = illiquidity.shift(1).rolling(
        7 * BARS_PER_DAY, min_periods=BARS_PER_DAY
    ).median()
    illiquidity_ratio = _safe_ratio(illiquidity, illiquidity_median)
    for threshold in (4.0, 8.0, 12.0):
        raw = direction.where(
            (illiquidity_ratio >= threshold)
            & (qv_ratio <= 0.8)
            & (return_z >= 1.5)
            & valid,
            0.0,
        )
        candidates.append(Candidate("liquidity_vacuum", f"ratio={threshold:g}", raw))

    # A multi-bar tail shock followed by a partial opposite bar tests recovery vs failure.
    prior_shock = returns.shift(1).rolling(3, min_periods=3).sum()
    shock_z = _safe_ratio(prior_shock.abs(), trailing_sigma * math.sqrt(3.0))
    recovery_fraction = _safe_ratio(abs_returns, prior_shock.abs())
    opposite = np.sign(returns) == -np.sign(prior_shock)
    for threshold in (2.5, 3.5, 4.5):
        raw = (-np.sign(prior_shock)).where(
            (shock_z >= threshold)
            & opposite
            & (recovery_fraction >= 0.15)
            & (recovery_fraction <= 0.80)
            & valid,
            0.0,
        )
        candidates.append(Candidate("tail_recovery", f"z={threshold:g}", raw))

    return candidates


def downside_recovery_refinement(frame: pd.DataFrame, round_trip_cost: float) -> list[Trial]:
    """Adaptive refinement of the informative long side of tail recovery."""
    returns = np.log(frame.close.astype(float) / frame.close.astype(float).shift(1))
    trailing_sigma = returns.shift(1).rolling(
        7 * BARS_PER_DAY, min_periods=7 * BARS_PER_DAY
    ).std()
    valid = (frame.volume > 0.0) & (frame.quote_volume > 0.0)
    trials: list[Trial] = []
    for shock_window in (2, 3, 4, 6):
        prior_shock = returns.shift(1).rolling(shock_window, min_periods=shock_window).sum()
        shock_z = _safe_ratio(
            prior_shock.abs(), trailing_sigma * math.sqrt(float(shock_window))
        )
        recovery_fraction = _safe_ratio(returns.abs(), prior_shock.abs())
        valid_shock_path = (
            frame.volume.rolling(shock_window + 1, min_periods=shock_window + 1).min() > 0.0
        ) & (
            frame.quote_volume.rolling(
                shock_window + 1, min_periods=shock_window + 1
            ).min()
            > 0.0
        )
        for threshold in (3.5, 4.0, 4.5, 5.0, 5.5):
            for recovery_floor in (0.10, 0.20, 0.30):
                signal = pd.Series(1.0, index=frame.index).where(
                    (prior_shock < 0.0)
                    & (returns > 0.0)
                    & (shock_z >= threshold)
                    & (recovery_fraction >= recovery_floor)
                    & (recovery_fraction <= 0.80)
                    & valid
                    & valid_shock_path,
                    0.0,
                )
                variant = (
                    f"window={shock_window},z={threshold:g},recovery={recovery_floor:g}"
                )
                for hold_bars in (12, 18, 24, 30, 36, 48, 72):
                    trials.append(
                        evaluate_signal(
                            frame,
                            family="downside_recovery_refinement",
                            variant=variant,
                            signal=signal,
                            hold_bars=hold_bars,
                            orientation=1.0,
                            round_trip_cost=round_trip_cost,
                        )
                    )
    return sorted(
        trials,
        key=lambda trial: (
            trial.positive_years,
            trial.sharpe,
            trial.mean_net_bps,
            trial.events,
        ),
        reverse=True,
    )


def evaluate_signal(
    frame: pd.DataFrame,
    *,
    family: str,
    variant: str,
    signal: pd.Series,
    hold_bars: int,
    orientation: float,
    round_trip_cost: float,
) -> Trial:
    opens = frame.open.to_numpy(dtype=float)
    values = signal.fillna(0.0).to_numpy(dtype=float) * orientation
    entries: list[int] = []
    decision = 0
    last_decision = len(frame) - hold_bars - 2
    while decision <= last_decision:
        if values[decision] != 0.0:
            entries.append(decision)
            decision += hold_bars + 1
        else:
            decision += 1

    positions = np.asarray(entries, dtype=int)
    if len(positions):
        entry_open = opens[positions + 1]
        exit_open = opens[positions + 1 + hold_bars]
        gross = values[positions] * (exit_open / entry_open - 1.0)
        net = gross - round_trip_cost
        entry_times = frame.index[positions + 1]
    else:
        net = np.empty(0, dtype=float)
        entry_times = pd.DatetimeIndex([])

    pnl_by_bar = np.zeros(len(frame), dtype=float)
    if len(positions):
        pnl_by_bar[positions + 1 + hold_bars] = net
    equity = np.cumprod(1.0 + pnl_by_bar)
    peaks = np.maximum.accumulate(np.r_[1.0, equity])
    max_drawdown = float(np.min(np.r_[1.0, equity] / peaks - 1.0))
    daily = (1.0 + pd.Series(pnl_by_bar, index=frame.index)).resample("1D").prod() - 1.0
    deviation = float(daily.std(ddof=1))
    sharpe = float(daily.mean() / deviation * math.sqrt(365.0)) if deviation > 0.0 else 0.0

    year_returns: dict[str, float] = {}
    for year in sorted(set(frame.index.year)):
        mask = entry_times.year == year
        if bool(np.any(mask)):
            year_returns[str(year)] = float(np.prod(1.0 + net[mask]) - 1.0)
    positive = net[net > 0.0]
    negative = net[net < 0.0]
    profit_factor = float(positive.sum() / abs(negative.sum())) if len(negative) else 0.0
    return Trial(
        family=family,
        variant=variant,
        orientation="native" if orientation > 0.0 else "inverse",
        hold_bars=hold_bars,
        events=len(net),
        mean_net_bps=float(net.mean() * 10_000.0) if len(net) else 0.0,
        win_rate=float(np.mean(net > 0.0)) if len(net) else 0.0,
        profit_factor=profit_factor,
        total_return=float(equity[-1] - 1.0),
        sharpe=sharpe,
        max_drawdown=max_drawdown,
        positive_years=sum(value > 0.0 for value in year_returns.values()),
        active_years=len(year_returns),
        year_returns=year_returns,
    )


def run(db_path: Path, round_trip_cost: float = DEFAULT_COST) -> dict:
    frame = load_bars(db_path)
    candidates = build_candidate_signals(frame)
    trials: list[Trial] = []
    for candidate in candidates:
        for hold_bars in (6, 12, 24, 48):
            for orientation in (1.0, -1.0):
                trials.append(
                    evaluate_signal(
                        frame,
                        family=candidate.family,
                        variant=candidate.variant,
                        signal=candidate.signal,
                        hold_bars=hold_bars,
                        orientation=orientation,
                        round_trip_cost=round_trip_cost,
                    )
                )
    ranked = sorted(
        trials,
        key=lambda trial: (
            trial.positive_years,
            trial.sharpe,
            trial.mean_net_bps,
            trial.events,
        ),
        reverse=True,
    )
    family_best: dict[str, dict] = {}
    for trial in ranked:
        family_best.setdefault(trial.family, asdict(trial))
    refinement = downside_recovery_refinement(frame, round_trip_cost)
    return {
        "study": "doge-intraday-open-frontier-v2",
        "mode": "adaptive_open_exploration_not_confirmation",
        "executed_at": datetime.now(UTC).isoformat(),
        "data": {
            "instrument": "DOGE-USDT-SWAP",
            "timeframe": "5m",
            "start": frame.index[0].isoformat(),
            "end_inclusive": frame.index[-1].isoformat(),
            "bars": len(frame),
            "untouched_holdout": False,
        },
        "execution": {
            "signal": "5m bar close",
            "entry": "next 5m bar open",
            "exit": "fixed future 5m bar open",
            "round_trip_cost_bps": round_trip_cost * 10_000.0,
        },
        "search": {
            "families": sorted({candidate.family for candidate in candidates}),
            "signal_variants": len(candidates),
            "holds_bars": [6, 12, 24, 48],
            "orientations": ["native", "inverse"],
            "trial_count": len(trials),
        },
        "family_best": family_best,
        "adaptive_refinement": {
            "parent_family": "tail_recovery",
            "reason": (
                "the downside-shock long side had positive net expectancy while the "
                "upside-shock short side was persistently negative"
            ),
            "trial_count": len(refinement),
            "top_30": [asdict(trial) for trial in refinement[:30]],
            "trials": [asdict(trial) for trial in refinement],
        },
        "top_30": [asdict(trial) for trial in ranked[:30]],
        "trials": [asdict(trial) for trial in trials],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("data/cq.db"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/research/doge_intraday_open_frontier_v2.json"),
    )
    args = parser.parse_args()
    report = run(args.db)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"search": report["search"], "family_best": report["family_best"]}, indent=2))


if __name__ == "__main__":
    main()
