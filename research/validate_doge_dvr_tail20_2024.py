#!/usr/bin/env python
"""One-shot 2024 validation of the pre-2024 selected DOGE DVR-T20."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from cq.context import Context, Series, series_fingerprint
from cq.core.types import CostModel, Intent, MarketSpec, Sizing
from cq.data.feed import load_series
from cq.data.store import Store
from cq.engine.loop import RunResult, run_backtest
from cq.research.metrics import compute_metrics, episode_returns, trades_from_fills
from cq.research.split import from_ms, to_ms
from cq.research.stats import bootstrap_trades
from cq.strategy.doge_dvr import DogeDvrConfig, DogeDvrTail20

DB_PATH = "data/cq.db"
INSTRUMENT = "DOGE-USDT"
TIMEFRAME = "1d"
VALIDATION_START = "2024-01-01"
VALIDATION_END = "2025-01-01"
INITIAL_CASH = 10_000.0
BASE_FEE_BPS = 10.0
BASE_SLIPPAGE_BPS = 5.0
STRESS_SLIPPAGE_BPS = 15.0
SEED = 20260722
STRATEGY_SOURCE = Path("cq/strategy/doge_dvr.py")
OUTPUT_JSON = Path("reports/research/doge_dvr_tail20_validation_2024.json")
OUTPUT_MD = Path(
    "docs/research/doge-spot/DVR_TAIL20_VALIDATION_2024_RESULTS_2026-07-22.md"
)


class WindowedDvr:
    """Expose warmup history but keep the portfolio flat outside 2024."""

    def __init__(self, start_ms: int, end_ms: int):
        self.inner = DogeDvrTail20()
        self.start_ms = start_ms
        self.end_ms = end_ms

    @property
    def name(self) -> str:
        return f"{self.inner.name}-windowed-2024"

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
        WindowedDvr(to_ms(VALIDATION_START), to_ms(VALIDATION_END)),
        series,
        MarketSpec(INSTRUMENT, "spot"),
        INITIAL_CASH,
        costs=CostModel(fee_bps=BASE_FEE_BPS, slippage_bps=slippage_bps),
        sizing=Sizing.ON_ENTRY,
    )


def _window_summary(result: RunResult) -> dict[str, Any]:
    start_ms = to_ms(VALIDATION_START)
    end_ms = to_ms(VALIDATION_END)
    indexes = [
        index
        for index, ts in enumerate(result.timestamps)
        if start_ms <= int(ts) < end_ms
    ]
    if not indexes:
        raise RuntimeError("2024 validation window is empty")
    timestamps = [result.timestamps[index] for index in indexes]
    equity = [result.equity[index] for index in indexes]
    fills = [fill for fill in result.fills if start_ms <= fill.ts < end_ms]
    opening = result.equity[indexes[0] - 1] if indexes[0] > 0 else INITIAL_CASH
    metrics = compute_metrics(timestamps, equity, fills, opening)
    episodes = episode_returns(timestamps, equity, fills, opening)
    bootstrap = bootstrap_trades(episodes, samples=10_000, seed=SEED)
    trades = trades_from_fills(fills)
    net = sorted((trade.net_pnl for trade in trades), reverse=True)
    return {
        "return": equity[-1] / opening - 1.0,
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
            (equity[-1] - (net[0] if net else 0.0)) / opening - 1.0
        ),
        "episode_count": len(episodes),
        "bootstrap_probability_of_loss": bootstrap.probability_of_loss,
        "bootstrap_p05": bootstrap.percentile_05,
        "bootstrap_median": bootstrap.median,
        "bootstrap_p95": bootstrap.percentile_95,
    }


def _gate(main: dict[str, Any], stress: dict[str, Any]) -> dict[str, Any]:
    checks = [
        ("15 bps return > 0", main["return"] > 0),
        ("15 bps Sharpe >= 0.40", main["sharpe"] >= 0.40),
        ("MaxDD <= 25%", main["max_drawdown"] <= 0.25),
        ("25 bps/side return > 0", stress["return"] > 0),
        ("return less best closed trade > 0", main["return_less_best_1"] > 0),
        ("at least four closed trades", main["trades"] >= 4),
    ]
    return {
        "passed": all(bool(value) for _, value in checks),
        "verdict": "VALIDATION PASS"
        if all(bool(value) for _, value in checks)
        else "VALIDATION FAIL",
        "checks": [
            {"name": name, "passed": bool(value)} for name, value in checks
        ],
    }


def _pct(value: float) -> str:
    return f"{value * 100:+.2f}%"


def _render(payload: dict[str, Any]) -> str:
    main = payload["main"]
    stress = payload["stress_25bps"]
    lines = [
        "# DOGE DVR-T20 2024 顺序验证结果",
        "",
        "> DVR-T20 从2021-2023 discovery事后晋级; 本报告是第一次打开2024。",
        "",
        f"**{payload['gate']['verdict']}**",
        "",
        "| Return | Sharpe | MaxDD | Trades | Less best 1 | 25bps return |",
        "|---:|---:|---:|---:|---:|---:|",
        (
            f"| {_pct(main['return'])} | {main['sharpe']:.2f} | "
            f"{_pct(-main['max_drawdown'])} | {main['trades']} | "
            f"{_pct(main['return_less_best_1'])} | {_pct(stress['return'])} |"
        ),
        "",
        "## 冻结门",
        "",
    ]
    lines.extend(
        f"- {'PASS' if check['passed'] else 'FAIL'} - {check['name']}"
        for check in payload["gate"]["checks"]
    )
    lines += [
        "",
        "## 其他统计",
        "",
        f"- Win rate: `{_pct(main['win_rate'])}`",
        f"- Profit factor: `{main['profit_factor']:.2f}`",
        f"- Bootstrap P5: `{_pct(main['bootstrap_p05'])}`",
        f"- Bootstrap P(loss): `{_pct(main['bootstrap_probability_of_loss'])}`",
        f"- Open position at year end: `{main['open_position_at_end']}`",
        "",
        "## Provenance",
        "",
        f"- Data fingerprint: `{payload['data_fingerprint']}`",
        f"- Strategy source SHA256: `{payload['strategy_source_sha256']}`",
        f"- Bars loaded: {payload['bars']}",
        f"- Range loaded: `{payload['range']}`",
        "- Query hard end: `2025-01-01 00:00 UTC` (exclusive)",
        "- Evaluation: cold-start `2024-01-01 .. 2025-01-01`",
        "- Execution: closed 1d decision, next 1d open fill, ON_ENTRY",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    end_ms = to_ms(VALIDATION_END)
    with Store(DB_PATH) as store:
        series = load_series(store, INSTRUMENT, TIMEFRAME, end_ms=end_ms)
    if len(series) == 0:
        raise SystemExit("DOGE-USDT validation data missing")
    if int(series.ts[-1]) >= end_ms:
        raise RuntimeError("2024 validation query crossed the frozen 2025 boundary")

    main = _window_summary(_run(series, BASE_SLIPPAGE_BPS))
    stress = _window_summary(_run(series, STRESS_SLIPPAGE_BPS))
    payload: dict[str, Any] = {
        "study": "doge-dvr-tail20-v1",
        "stage": "2024_validation",
        "accessed_at": dt.datetime.now(dt.UTC).isoformat(),
        "params": asdict(DogeDvrConfig()),
        "data_fingerprint": series_fingerprint(series),
        "strategy_source_sha256": hashlib.sha256(
            STRATEGY_SOURCE.read_bytes()
        ).hexdigest(),
        "bars": len(series),
        "range": f"{from_ms(int(series.ts[0]))}..{from_ms(int(series.ts[-1]))}",
        "main": main,
        "stress_25bps": stress,
        "gate": _gate(main, stress),
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
