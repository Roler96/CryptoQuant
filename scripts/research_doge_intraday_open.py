"""Open DOGE-only intraday mechanism exploration.

This is adaptive discovery, not confirmatory evidence. It reads only the historical
research pool ending before 2025-06-01 and records every tested variant.
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

from cq.context import Series
from cq.core.types import CostModel, MarketSpec, Sizing
from cq.engine.loop import RunResult, run_backtest
from cq.research.coherent_path import CoherentPathConfig, CoherentPathStrategy

START = "2021-01-01T00:00:00Z"
END = "2025-06-01T00:00:00Z"
START_MS = int(pd.Timestamp(START).timestamp() * 1000)
END_MS = int(pd.Timestamp(END).timestamp() * 1000)
ROUND_TRIP_COST = 0.003


@dataclass(frozen=True)
class Trial:
    family: str
    window: int
    hold: int
    threshold: float
    side: str
    events: int
    mean_net_bps: float
    win_rate: float
    profit_factor: float
    total_return: float
    sharpe: float
    max_drawdown: float
    positive_segments: int
    segment_returns: dict[str, float]


def load_bars(db_path: Path) -> pd.DataFrame:
    connection = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    try:
        frame = pd.read_sql_query(
            """SELECT ts, open, high, low, close, volume, quote_volume
               FROM ohlcv
               WHERE inst_id='DOGE-USDT-SWAP' AND timeframe='5m'
                 AND ts>=? AND ts<? ORDER BY ts""",
            connection,
            params=(START_MS, END_MS),
        )
    finally:
        connection.close()
    if frame.empty:
        raise RuntimeError("DOGE research query returned no bars")
    expected = np.arange(frame.ts.iloc[0], frame.ts.iloc[-1] + 300_000, 300_000)
    if len(expected) != len(frame) or not np.array_equal(expected, frame.ts.to_numpy()):
        raise RuntimeError("native DOGE 5m bars are not contiguous")
    index = pd.to_datetime(frame.pop("ts"), unit="ms", utc=True)
    frame.index = index
    if not np.isfinite(frame.to_numpy(dtype=float)).all():
        raise RuntimeError("non-finite DOGE input")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise RuntimeError("non-positive DOGE prices")
    return frame


def resample_15m(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.resample("15min", label="left", closed="left", origin="epoch").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        quote_volume=("quote_volume", "sum"),
    )
    if result.isna().any().any():
        raise RuntimeError("15m aggregation produced missing bars")
    return result


def causal_features(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    returns = np.log(out.close / out.close.shift(1))
    out["ret"] = returns
    out["abs_ret"] = returns.abs()
    out["sq_ret"] = returns.pow(2)
    out["signed_qv"] = np.sign(returns) * out.quote_volume
    return out


def candidate_signals(frame: pd.DataFrame):
    r = frame.ret
    abs_r = frame.abs_ret
    sq_r = frame.sq_ret
    qv = frame.quote_volume
    signed_qv = frame.signed_qv

    for window in (8, 16, 32):
        net = r.rolling(window).sum()
        gross = abs_r.rolling(window).sum()
        efficiency = net.abs() / gross.replace(0.0, np.nan)
        direction = np.sign(net)
        valid_window = (
            (frame.volume.rolling(window).min() > 0.0)
            & (frame.quote_volume.rolling(window).min() > 0.0)
        )
        history = 30 * 24 * 4

        # Low-entropy directional paths: continuation versus explicit reversal.
        for threshold in (0.55, 0.70, 0.82):
            raw = direction.where((efficiency >= threshold) & valid_window, 0.0)
            yield "coherent_path", window, threshold, raw

        positive_sv = sq_r.where(r > 0, 0.0).rolling(window).sum()
        negative_sv = sq_r.where(r < 0, 0.0).rolling(window).sum()
        imbalance = (positive_sv - negative_sv) / (positive_sv + negative_sv).replace(
            0.0, np.nan
        )
        displacement = net.abs() / gross.replace(0.0, np.nan)
        for threshold in (0.55, 0.70, 0.82):
            # Directional realized variance with poor net progress: test whether
            # inventory pressure resolves in the same or opposite direction.
            raw = np.sign(imbalance).where(
                (imbalance.abs() >= threshold)
                & (displacement <= 0.45)
                & valid_window,
                0.0,
            )
            yield "frustrated_semivariance", window, threshold, raw

        signed_flow = signed_qv.rolling(window).sum()
        total_flow = qv.rolling(window).sum()
        flow_imbalance = signed_flow / total_flow.replace(0.0, np.nan)
        price_z = net / r.rolling(history, min_periods=window * 4).std(ddof=1).replace(
            0.0, np.nan
        )
        for threshold in (0.20, 0.35, 0.50):
            # Strong signed turnover but muted displacement is a multi-bar
            # price-impact elasticity state, not a one-bar volume spike.
            raw = np.sign(flow_imbalance).where(
                (flow_imbalance.abs() >= threshold)
                & (price_z.abs() <= 1.0)
                & valid_window,
                0.0,
            )
            yield "muted_flow_impact", window, threshold, raw

        short = max(4, window // 4)
        short_rv = sq_r.rolling(short).sum()
        long_rv = sq_r.rolling(window).sum() * short / window
        transition = short_rv / long_rv.replace(0.0, np.nan)
        efficiency_floor = 0.45
        for threshold in (1.5, 2.0, 3.0):
            raw = direction.where(
                (transition >= threshold)
                & (efficiency >= efficiency_floor)
                & valid_window,
                0.0,
            )
            yield "volatility_transition", window, threshold, raw


def evaluate(
    frame: pd.DataFrame,
    family: str,
    window: int,
    hold: int,
    threshold: float,
    raw_signal: pd.Series,
    orientation: float,
) -> Trial:
    opens = frame.open.to_numpy(dtype=float)
    signal = raw_signal.fillna(0.0).to_numpy(dtype=float) * orientation
    entries: list[int] = []
    i = window - 1
    last_decision = len(frame) - hold - 2
    while i <= last_decision:
        if signal[i] != 0.0:
            entries.append(i)
            i += hold + 1
        else:
            i += 1
    if not entries:
        net = np.empty(0)
        times = pd.DatetimeIndex([])
    else:
        positions = np.asarray(entries, dtype=int)
        entry_open = opens[positions + 1]
        exit_open = opens[positions + 1 + hold]
        gross = signal[positions] * (exit_open / entry_open - 1.0)
        net = gross - ROUND_TRIP_COST
        times = frame.index[positions + 1]

    equity = np.ones(len(frame), dtype=float)
    pnl_by_bar = np.zeros(len(frame), dtype=float)
    for decision, value in zip(entries, net, strict=True):
        pnl_by_bar[decision + 1 + hold] += value
    equity = np.cumprod(1.0 + pnl_by_bar)
    peaks = np.maximum.accumulate(np.r_[1.0, equity])
    max_drawdown = float(np.min(np.r_[1.0, equity] / peaks - 1.0))
    daily = (1.0 + pd.Series(pnl_by_bar, index=frame.index)).resample("1D").prod() - 1.0
    std = float(daily.std(ddof=1))
    sharpe = float(daily.mean() / std * math.sqrt(365.0)) if std > 0 else 0.0
    segments: dict[str, float] = {}
    for label, start, end in (
        ("2021", "2021-01-01", "2022-01-01"),
        ("2022", "2022-01-01", "2023-01-01"),
        ("2023", "2023-01-01", "2024-01-01"),
        ("2024", "2024-01-01", "2025-01-01"),
        ("2025-partial", "2025-01-01", "2025-06-01"),
    ):
        mask = (times >= start) & (times < end)
        segments[label] = float(np.prod(1.0 + net[mask]) - 1.0) if len(net) else 0.0
    positives = net[net > 0]
    negatives = net[net < 0]
    profit_factor = (
        float(positives.sum() / abs(negatives.sum())) if len(negatives) else 0.0
    )
    return Trial(
        family=family,
        window=window,
        hold=hold,
        threshold=threshold,
        side="continuation" if orientation > 0 else "reversal",
        events=len(net),
        mean_net_bps=float(net.mean() * 10_000) if len(net) else 0.0,
        win_rate=float(np.mean(net > 0)) if len(net) else 0.0,
        profit_factor=profit_factor,
        total_return=float(equity[-1] - 1.0),
        sharpe=sharpe,
        max_drawdown=max_drawdown,
        positive_segments=sum(value > 0 for value in segments.values()),
        segment_returns=segments,
    )


def run(db_path: Path) -> dict:
    native = load_bars(db_path)
    frame = causal_features(resample_15m(native))
    trials: list[Trial] = []
    for family, window, threshold, raw in candidate_signals(frame):
        for hold in (4, 8, 16, 32):
            for orientation in (1.0, -1.0):
                trials.append(
                    evaluate(frame, family, window, hold, threshold, raw, orientation)
                )
    ranked = sorted(
        trials,
        key=lambda trial: (
            trial.positive_segments,
            trial.sharpe,
            trial.mean_net_bps,
        ),
        reverse=True,
    )
    family_best = {}
    for trial in ranked:
        family_best.setdefault(trial.family, asdict(trial))
    refinement = coherent_path_refinement(frame)
    engine_validation = validate_candidate_with_engine(frame)
    return {
        "study": "doge-intraday-open-exploration-v1",
        "mode": "adaptive_open_exploration_not_confirmation",
        "executed_at": datetime.now(UTC).isoformat(),
        "data": {
            "instrument": "DOGE-USDT-SWAP",
            "native_timeframe": "5m",
            "decision_timeframe": "15m",
            "start": START,
            "end_exclusive": END,
            "native_bars": len(native),
            "decision_bars": len(frame),
            "holdout_accessed": False,
        },
        "execution": {
            "signal": "15m bar close",
            "entry": "next 15m bar open",
            "exit": "fixed future 15m bar open",
            "fee_plus_slippage_bps_per_side": 15.0,
        },
        "trial_count": len(trials),
        "family_best": family_best,
        "adaptive_refinement": {
            "parent_family": "coherent_path",
            "reason": "only family with five positive calendar segments in stage 1",
            "trial_count": len(refinement),
            "top_20": [asdict(trial) for trial in refinement[:20]],
            "trials": [asdict(trial) for trial in refinement],
        },
        "engine_validation": engine_validation,
        "top_20": [asdict(trial) for trial in ranked[:20]],
        "trials": [asdict(trial) for trial in trials],
    }


def coherent_path_refinement(frame: pd.DataFrame) -> list[Trial]:
    """Adaptive local grid around the stage-one coherent-path survivor."""
    trials: list[Trial] = []
    for window in (12, 14, 16, 18, 20, 24):
        net = frame.ret.rolling(window).sum()
        gross = frame.abs_ret.rolling(window).sum()
        efficiency = net.abs() / gross.replace(0.0, np.nan)
        direction = np.sign(net)
        valid_window = (
            (frame.volume.rolling(window).min() > 0.0)
            & (frame.quote_volume.rolling(window).min() > 0.0)
        )
        for threshold in (0.72, 0.75, 0.78, 0.80, 0.82, 0.84, 0.86, 0.88):
            raw = direction.where((efficiency >= threshold) & valid_window, 0.0)
            for hold in (4, 8, 12, 16):
                trials.append(
                    evaluate(
                        frame,
                        "coherent_path_refinement",
                        window,
                        hold,
                        threshold,
                        raw,
                        -1.0,
                    )
                )
    return sorted(
        trials,
        key=lambda trial: (
            trial.positive_segments,
            trial.sharpe,
            trial.mean_net_bps,
        ),
        reverse=True,
    )


def validate_candidate_with_engine(frame: pd.DataFrame) -> dict:
    """Validate the adaptive survivor with the shared causal engine."""
    series = _to_series(frame)
    config = CoherentPathConfig(
        window_bars=18,
        efficiency_threshold=0.78,
        hold_bars=12,
        target_weight=0.25,
        evaluation_end_ms=END_MS,
    )
    main = _run_engine(series, config, CostModel(fee_bps=10.0, slippage_bps=5.0))
    stress = _run_engine(series, config, CostModel(fee_bps=15.0, slippage_bps=10.0))

    segments = {}
    for label, start, end in (
        ("2021", "2021-01-01T00:00:00Z", "2022-01-01T00:00:00Z"),
        ("2022", "2022-01-01T00:00:00Z", "2023-01-01T00:00:00Z"),
        ("2023", "2023-01-01T00:00:00Z", "2024-01-01T00:00:00Z"),
        ("2024", "2024-01-01T00:00:00Z", "2025-01-01T00:00:00Z"),
        ("2025-partial", "2025-01-01T00:00:00Z", END),
    ):
        start_ms = int(pd.Timestamp(start).value // 1_000_000)
        end_ms = int(pd.Timestamp(end).value // 1_000_000)
        segment = _slice_with_warmup(series, start_ms, end_ms, config.window_bars + 1)
        segment_config = CoherentPathConfig(
            window_bars=config.window_bars,
            efficiency_threshold=config.efficiency_threshold,
            hold_bars=config.hold_bars,
            target_weight=config.target_weight,
            evaluation_start_ms=start_ms,
            evaluation_end_ms=end_ms,
        )
        segments[label] = _engine_metrics(
            _run_engine(
                segment,
                segment_config,
                CostModel(fee_bps=10.0, slippage_bps=5.0),
            )
        )

    return {
        "candidate": "coherent-path-exhaustion-reversal",
        "selection_lineage": {
            "stage_1_trials": 288,
            "adaptive_refinement_trials": 192,
            "selection_rule": (
                "five positive calendar segments, zero invalid entry/exit bars, "
                "then plateau-centered window/threshold/hold"
            ),
        },
        "config": asdict(config),
        "funding": "off; unavailable for the 2021-2025 research pool",
        "main_15bps_per_side": _engine_metrics(main),
        "stress_25bps_per_side": _engine_metrics(stress),
        "calendar_cold_starts": segments,
        "integrity": {
            "primary_fingerprint": main.manifest.primary_fingerprint,
            "engine_version": main.manifest.engine_version,
            "main_rejections": len(main.rejections),
            "stress_rejections": len(stress.rejections),
            "main_final_flat": main.portfolio.is_flat,
            "stress_final_flat": stress.portfolio.is_flat,
            "main_fill_reasons": _counts(fill.reason for fill in main.fills),
            "holdout_accessed": False,
        },
    }


def _to_series(frame: pd.DataFrame) -> Series:
    return Series(
        "DOGE-USDT-SWAP",
        "15m",
        np.asarray(frame.index.view("int64") // 1_000_000, dtype=np.int64),
        frame.open.to_numpy(dtype=float),
        frame.high.to_numpy(dtype=float),
        frame.low.to_numpy(dtype=float),
        frame.close.to_numpy(dtype=float),
        frame.volume.to_numpy(dtype=float),
    )


def _slice_with_warmup(series: Series, start_ms: int, end_ms: int, warmup: int) -> Series:
    start_index = int(np.searchsorted(series.ts, start_ms, side="left"))
    lower = max(0, start_index - warmup)
    upper = int(np.searchsorted(series.ts, end_ms, side="left"))
    return Series(
        series.inst_id,
        series.timeframe,
        series.ts[lower:upper],
        series.open[lower:upper],
        series.high[lower:upper],
        series.low[lower:upper],
        series.close[lower:upper],
        series.volume[lower:upper],
    )


def _run_engine(series: Series, config: CoherentPathConfig, costs: CostModel) -> RunResult:
    return run_backtest(
        CoherentPathStrategy(config),
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
        costs=costs,
        sizing=Sizing.ON_ENTRY,
        dust_fraction=0.0,
        evaluation_start_ms=config.evaluation_start_ms,
    )


def _engine_metrics(result: RunResult) -> dict:
    if result.rejections:
        raise RuntimeError(f"engine rejected {len(result.rejections)} candidate orders")
    if not result.portfolio.is_flat:
        raise RuntimeError("candidate engine run ended with an open position")
    filled = [record for record in result.transactions if record.status == "filled"]
    if len(filled) % 2:
        raise RuntimeError("candidate engine run has an odd fill count")

    episode_pnls: list[float] = []
    long_pnls: list[float] = []
    short_pnls: list[float] = []
    for index in range(0, len(filled), 2):
        entry, exit_ = filled[index : index + 2]
        pnl = exit_.equity_after - entry.equity_before
        episode_pnls.append(pnl)
        (long_pnls if entry.side == "buy" else short_pnls).append(pnl)

    equity = np.asarray([result.initial_cash, *result.equity], dtype=float)
    running_max = np.maximum.accumulate(equity)
    max_drawdown = float(np.min(equity / running_max - 1.0))
    marks = pd.Series(
        result.equity,
        index=pd.to_datetime(result.timestamps, unit="ms", utc=True),
        dtype=float,
    ).resample("1D").last()
    daily = marks.pct_change()
    if len(daily):
        daily.iloc[0] = marks.iloc[0] / result.initial_cash - 1.0
    deviation = float(daily.std(ddof=1)) if len(daily) >= 2 else 0.0
    sharpe = float(daily.mean() / deviation * math.sqrt(365.0)) if deviation > 0 else 0.0
    pnls = np.asarray(episode_pnls, dtype=float)
    positive = float(pnls[pnls > 0.0].sum())
    negative = float(pnls[pnls < 0.0].sum())
    return {
        "return": result.total_return,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "episodes": len(episode_pnls),
        "fills": len(result.fills),
        "win_rate": float(np.mean(pnls > 0.0)) if len(pnls) else 0.0,
        "profit_factor": positive / abs(negative) if negative < 0.0 else 0.0,
        "long_episodes": len(long_pnls),
        "long_pnl": float(sum(long_pnls)),
        "short_episodes": len(short_pnls),
        "short_pnl": float(sum(short_pnls)),
        "best_1_positive_pnl_share": _positive_concentration(pnls, 1),
        "best_3_positive_pnl_share": _positive_concentration(pnls, 3),
        "best_5_positive_pnl_share": _positive_concentration(pnls, 5),
    }


def _positive_concentration(pnls: np.ndarray, count: int) -> float | None:
    positive = np.sort(pnls[pnls > 0.0])[::-1]
    denominator = float(positive.sum())
    return float(positive[:count].sum() / denominator) if denominator > 0.0 else None


def _counts(values) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("data/cq.db"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/research/doge_intraday_open_exploration_v1.json"),
    )
    args = parser.parse_args()
    report = run(args.db)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({k: report[k] for k in ("study", "trial_count", "family_best")}, indent=2))


if __name__ == "__main__":
    main()
