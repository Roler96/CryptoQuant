#!/usr/bin/env python
"""Candidate-specific 2026 validation of the frozen DOGE DVR-T20.

The candidate already failed its 2025 pre-freeze gate.  This runner exists to
honour the requested frozen-parameter 2026 measurement; no 2026 outcome can
promote, modify, or rescue the strategy.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from cq.context import Context, Series, series_fingerprint
from cq.core.types import CostModel, Intent, MarketSpec, Sizing
from cq.data.feed import load_series
from cq.data.store import Store
from cq.engine.loop import RunResult, run_backtest
from cq.research.metrics import (
    compute_metrics,
    episode_returns,
    position_spans,
    trades_from_fills,
)
from cq.research.split import (
    holdout_access_count,
    record_holdout_access,
    to_ms,
)
from cq.research.stats import bootstrap_trades
from cq.strategy.doge_dvr import DogeDvrConfig, DogeDvrTail20

DB_PATH = "data/cq.db"
INSTRUMENT = "DOGE-USDT"
TIMEFRAME = "1d"
HOLDOUT_START = "2026-01-01"
HOLDOUT_END = "2027-01-01"
INITIAL_CASH = 10_000.0
BASE_FEE_BPS = 10.0
BASE_SLIPPAGE_BPS = 5.0
STRESS_SLIPPAGE_BPS = 15.0
SAMPLES = 10_000
SEED = 20260722
STUDY = "doge-dvr-tail20-v1-2026-candidate-holdout"
SPLIT_FINGERPRINT = "46405e6c105c2764"
STRATEGY_SOURCE = Path("cq/strategy/doge_dvr.py")
OUTPUT_JSON = Path("reports/research/doge_dvr_tail20_validation_2026.json")
OUTPUT_MD = Path(
    "docs/research/doge-spot/DVR_TAIL20_VALIDATION_2026_RESULTS_2026-07-22.md"
)


class WindowedDvr:
    def __init__(self, start_ms: int, end_ms: int):
        self.inner = DogeDvrTail20()
        self.start_ms = start_ms
        self.end_ms = end_ms

    @property
    def name(self) -> str:
        return f"{self.inner.name}-windowed-2026"

    @property
    def warmup_bars(self) -> int:
        return self.inner.warmup_bars

    def reset(self) -> None:
        self.inner.reset()

    def on_bar(self, ctx: Context) -> Intent:
        if ctx.decision_time < self.start_ms:
            return Intent(target=0.0, reason=f"{self.name}-before-window")
        if ctx.decision_time >= self.end_ms:
            return Intent(target=0.0, reason=f"{self.name}-after-window")
        return self.inner.on_bar(ctx)


def _run(series: Series, slippage_bps: float) -> RunResult:
    return run_backtest(
        WindowedDvr(to_ms(HOLDOUT_START), to_ms(HOLDOUT_END)),
        series,
        MarketSpec(INSTRUMENT, "spot"),
        INITIAL_CASH,
        costs=CostModel(fee_bps=BASE_FEE_BPS, slippage_bps=slippage_bps),
        sizing=Sizing.ON_ENTRY,
    )


def _window_data(
    result: RunResult,
) -> tuple[list[int], list[float], list[Any], float]:
    start_ms = to_ms(HOLDOUT_START)
    end_ms = to_ms(HOLDOUT_END)
    indexes = [
        index
        for index, ts in enumerate(result.timestamps)
        if start_ms <= int(ts) < end_ms
    ]
    if not indexes:
        raise RuntimeError("2026 validation window is empty")
    first = indexes[0]
    previous = first - 1
    opening = result.equity[previous] if previous >= 0 else INITIAL_CASH
    # Include the actual pre-window equity point so first-day return and
    # drawdown are part of Sharpe/MaxDD.  It is outside the evaluation return
    # numerator but inside the path, exactly as an opening cash observation.
    start_index = previous if previous >= 0 else first
    timestamps = result.timestamps[start_index : indexes[-1] + 1]
    equity = result.equity[start_index : indexes[-1] + 1]
    fills = [
        fill for fill in result.fills if start_ms <= fill.ts < end_ms
    ]
    return timestamps, equity, fills, opening


def _summary(result: RunResult) -> dict[str, Any]:
    timestamps, equity, fills, opening = _window_data(result)
    metrics = compute_metrics(timestamps, equity, fills, opening)
    episodes = episode_returns(timestamps, equity, fills, opening)
    bootstrap = bootstrap_trades(episodes, samples=SAMPLES, seed=SEED)
    trades = trades_from_fills(fills)
    net = sorted((trade.net_pnl for trade in trades), reverse=True)
    final = equity[-1]
    return {
        "return": final / opening - 1.0,
        "cagr": metrics.cagr,
        "sharpe": metrics.sharpe,
        "max_drawdown": metrics.max_drawdown,
        "longest_drawdown_days": metrics.longest_drawdown_days,
        "trades": metrics.trades,
        "win_rate": metrics.win_rate,
        "profit_factor": metrics.profit_factor,
        "fills": len(fills),
        "open_position_at_end": len(fills) % 2 == 1,
        "return_less_best_1": (
            (final - (net[0] if net else 0.0)) / opening - 1.0
        ),
        "episode_count": len(episodes),
        "bootstrap_probability_of_loss": bootstrap.probability_of_loss,
        "bootstrap_p05": bootstrap.percentile_05,
        "bootstrap_median": bootstrap.median,
        "bootstrap_p95": bootstrap.percentile_95,
        "trade_details": [
            {
                "entry_ts": trade.entry_ts,
                "exit_ts": trade.exit_ts,
                "return": trade.return_pct,
                "net_pnl": trade.net_pnl,
                "holding_days": trade.holding_ms / (24 * 60 * 60 * 1000),
            }
            for trade in trades
        ],
    }


def _matched_random_null(
    series: Series,
    spans: list[tuple[int, int | None]],
    observed: float,
    last_evaluation_index: int,
    samples: int = SAMPLES,
    seed: int = SEED,
) -> dict[str, float | int]:
    """Match 2026 holding days and preserve open-episode MTM semantics."""
    index_of = {int(ts): index for index, ts in enumerate(series.ts)}
    indexes = np.arange(len(series), dtype=int)
    start_index = int(np.searchsorted(series.ts, to_ms(HOLDOUT_START)))
    candidates_2026 = indexes[
        (indexes >= start_index) & (indexes <= last_evaluation_index)
    ]
    rng = np.random.default_rng(seed)
    totals = np.ones(samples, dtype=float)
    config = DogeDvrConfig()
    fee = BASE_FEE_BPS / 10_000
    slip = BASE_SLIPPAGE_BPS / 10_000

    for entry_ts, exit_ts in spans:
        entry_index = index_of[int(entry_ts)]
        is_open = exit_ts is None
        exit_index = (
            last_evaluation_index if is_open else index_of[int(exit_ts)]
        )
        holding_bars = exit_index - entry_index
        if holding_bars < 1:
            raise ValueError("matched episodes must hold at least one day")
        candidates = candidates_2026[
            candidates_2026 + holding_bars <= last_evaluation_index
        ]
        candidates = candidates[series.volume[candidates] > 0]
        if not is_open:
            candidates = candidates[
                series.volume[candidates + holding_bars] > 0
            ]
        if len(candidates) == 0:
            raise ValueError("no matched 2026 random entry candidates")
        starts = rng.choice(candidates, size=samples, replace=True)
        ends = starts + holding_bars
        gross_entry = (1.0 + slip) * (1.0 + fee)
        if is_open:
            gross_exit = series.close[ends] / series.open[starts]
        else:
            gross_exit = (
                series.open[ends]
                / series.open[starts]
                * (1.0 - slip)
                * (1.0 - fee)
            )
        totals *= 1.0 + config.size * (gross_exit - gross_entry)

    null_returns = totals - 1.0
    exceedances = int(np.sum(null_returns >= observed))
    return {
        "samples": samples,
        "episodes": len(spans),
        "observed": observed,
        "null_p05": float(np.percentile(null_returns, 5)),
        "null_median": float(np.median(null_returns)),
        "null_p95": float(np.percentile(null_returns, 95)),
        "p_value": (exceedances + 1) / (samples + 1),
    }


def _gate(main: dict[str, Any], stress: dict[str, Any], null: dict[str, Any]) -> dict[str, Any]:
    checks = [
        ("15 bps return > 0", main["return"] > 0),
        ("25 bps/side return > 0", stress["return"] > 0),
        ("MaxDD <= 20%", main["max_drawdown"] <= 0.20),
        ("at least four closed trades", main["trades"] >= 4),
        ("return less best closed trade > 0", main["return_less_best_1"] > 0),
        ("episode bootstrap P5 > 0", main["bootstrap_p05"] > 0),
        ("matched-random one-sided p < 0.10", null["p_value"] < 0.10),
    ]
    return {
        "passed": all(bool(value) for _, value in checks),
        "checks": [
            {"name": name, "passed": bool(value)} for name, value in checks
        ],
    }


def _pct(value: float) -> str:
    return f"{value * 100:+.2f}%"


def _render(payload: dict[str, Any]) -> str:
    main = payload["main"]
    stress = payload["stress_25bps"]
    null = payload["matched_random"]
    lines = [
        "# DOGE DVR-T20 2026 冻结验证",
        "",
        "> 策略已在2025 pre-freeze审计失败; 2026只作用户要求的冻结参数诊断, "
        "不能挽救或晋级策略。",
        "",
        f"**{payload['verdict']}**",
        "",
        f"数据覆盖: `{payload['holdout_coverage']}`",
        "",
        "| Return | Sharpe | MaxDD | Trades | Less best 1 | 25bps return |",
        "|---:|---:|---:|---:|---:|---:|",
        (
            f"| {_pct(main['return'])} | {main['sharpe']:.2f} | "
            f"{_pct(-main['max_drawdown'])} | {main['trades']} | "
            f"{_pct(main['return_less_best_1'])} | {_pct(stress['return'])} |"
        ),
        "",
        "## 完整年度冻结门 (当前只显示进度, 不裁决)",
        "",
    ]
    lines.extend(
        f"- {'PASS' if check['passed'] else 'FAIL'} - {check['name']}"
        for check in payload["gate"]["checks"]
    )
    lines += [
        "",
        "## 匹配随机入场",
        "",
        f"- Observed: `{_pct(float(null['observed']))}`",
        f"- Null median: `{_pct(float(null['null_median']))}`",
        f"- Null P5-P95: `{_pct(float(null['null_p05']))}` .. "
        f"`{_pct(float(null['null_p95']))}`",
        f"- One-sided p: `{float(null['p_value']):.6f}`",
        "",
        "## Provenance",
        "",
        f"- Data fingerprint: `{payload['data_fingerprint']}`",
        f"- Strategy source SHA256: `{payload['strategy_source_sha256']}`",
        f"- Holdout access count: {payload['holdout_access_count']}",
        f"- Split fingerprint: `{payload['split_fingerprint']}`",
        f"- Bars loaded: {payload['bars']}",
        f"- Range loaded: `{payload['range']}`",
        "- Query end fixed at `2027-01-01 00:00 UTC` (exclusive), not latest",
        "- Candidate-level decision remains REJECTED regardless of 2026",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    # Log the first candidate-specific holdout access before opening the DB.
    if holdout_access_count(STUDY) == 0:
        record_holdout_access(
            study=STUDY,
            segment="2026_frozen_validation",
            hypothesis=(
                "Measure the unchanged DVR-T20 on 2026 after its 2025 failure; "
                "the result is diagnostic only and cannot promote the strategy"
            ),
            fingerprint=SPLIT_FINGERPRINT,
        )

    end_ms = to_ms(HOLDOUT_END)
    with Store(DB_PATH) as store:
        series = load_series(store, INSTRUMENT, TIMEFRAME, end_ms=end_ms)
    if len(series) == 0:
        raise SystemExit("DOGE-USDT validation data missing")
    if int(series.ts[-1]) >= end_ms:
        raise RuntimeError("2026 validation query crossed the fixed 2027 boundary")

    main_result = _run(series, BASE_SLIPPAGE_BPS)
    main = _summary(main_result)
    stress = _summary(_run(series, STRESS_SLIPPAGE_BPS))
    evaluation_indexes = np.flatnonzero(series.ts >= to_ms(HOLDOUT_START))
    last_evaluation_index = int(evaluation_indexes[-1])
    spans = position_spans(main_result.fills)
    timestamps, equity, fills, opening = _window_data(main_result)
    episodes = episode_returns(timestamps, equity, fills, opening)
    if len(episodes) != len(spans):
        raise RuntimeError("2026 episode returns and spans disagree")
    observed = float(np.prod(1.0 + np.asarray(episodes)) - 1.0)
    random_null = _matched_random_null(
        series,
        spans,
        observed,
        last_evaluation_index,
    )
    gate = _gate(main, stress, random_null)
    complete = int(series.close_times[-1]) >= end_ms
    coverage_end = dt.datetime.fromtimestamp(
        int(series.close_times[-1]) / 1000,
        dt.UTC,
    ).isoformat()
    verdict = "FROZEN VALIDATION PASS" if gate["passed"] else "FROZEN VALIDATION FAIL"
    if not complete:
        verdict = "INCONCLUSIVE - 2026 INCOMPLETE"

    payload: dict[str, Any] = {
        "study": STUDY,
        "stage": "2026_frozen_validation",
        "accessed_at": dt.datetime.now(dt.UTC).isoformat(),
        "candidate_decision": "REJECTED_BY_2025_PRE_FREEZE_AUDIT",
        "params": asdict(DogeDvrConfig()),
        "complete_natural_year": complete,
        "holdout_coverage": f"{HOLDOUT_START}..{coverage_end}",
        "verdict": verdict,
        "data_fingerprint": series_fingerprint(series),
        "strategy_source_sha256": hashlib.sha256(
            STRATEGY_SOURCE.read_bytes()
        ).hexdigest(),
        "split_fingerprint": SPLIT_FINGERPRINT,
        "holdout_access_count": holdout_access_count(STUDY),
        "bars": len(series),
        "range": (
            f"{dt.datetime.fromtimestamp(int(series.ts[0]) / 1000, dt.UTC).isoformat()}.."
            f"{dt.datetime.fromtimestamp(int(series.ts[-1]) / 1000, dt.UTC).isoformat()}"
        ),
        "underlying_2026_return": (
            float(series.close[last_evaluation_index] / series.open[evaluation_indexes[0]] - 1.0)
        ),
        "main": main,
        "stress_25bps": stress,
        "matched_random": random_null,
        "gate": gate,
    }
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    OUTPUT_MD.write_text(_render(payload), encoding="utf-8")
    print(_render(payload))
    print(f"JSON: {OUTPUT_JSON}")
    print(f"REPORT: {OUTPUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
