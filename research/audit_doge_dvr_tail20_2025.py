#!/usr/bin/env python
"""One-shot 2025 pre-freeze audit for the unchanged DOGE DVR-T20."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
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
from cq.research.split import from_ms, to_ms
from cq.research.stats import bootstrap_trades
from cq.strategy.doge_dvr import DogeDvrConfig, DogeDvrTail20
from research.audit_doge_vcse_robustness import _block_bootstrap, _year_jackknife

DB_PATH = "data/cq.db"
INSTRUMENT = "DOGE-USDT"
TIMEFRAME = "1d"
AUDIT_START = "2025-01-01"
AUDIT_END = "2026-01-01"
INITIAL_CASH = 10_000.0
BASE_FEE_BPS = 10.0
BASE_SLIPPAGE_BPS = 5.0
STRESS_SLIPPAGE_BPS = 15.0
SAMPLES = 10_000
SEED = 20260722
STRATEGY_SOURCE = Path("cq/strategy/doge_dvr.py")
OUTPUT_JSON = Path("reports/research/doge_dvr_tail20_audit_2025.json")
OUTPUT_MD = Path(
    "docs/research/doge-spot/DVR_TAIL20_AUDIT_2025_RESULTS_2026-07-22.md"
)


class WindowedDvr:
    def __init__(self, start_ms: int, end_ms: int):
        self.inner = DogeDvrTail20()
        self.start_ms = start_ms
        self.end_ms = end_ms

    @property
    def name(self) -> str:
        return f"{self.inner.name}-windowed-2025"

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


def _run_window(series: Series, slippage_bps: float) -> RunResult:
    return run_backtest(
        WindowedDvr(to_ms(AUDIT_START), to_ms(AUDIT_END)),
        series,
        MarketSpec(INSTRUMENT, "spot"),
        INITIAL_CASH,
        costs=CostModel(fee_bps=BASE_FEE_BPS, slippage_bps=slippage_bps),
        sizing=Sizing.ON_ENTRY,
    )


def _run_full(series: Series) -> RunResult:
    return run_backtest(
        DogeDvrTail20(),
        series,
        MarketSpec(INSTRUMENT, "spot"),
        INITIAL_CASH,
        costs=CostModel(
            fee_bps=BASE_FEE_BPS,
            slippage_bps=BASE_SLIPPAGE_BPS,
        ),
        sizing=Sizing.ON_ENTRY,
    )


def _window_summary(result: RunResult) -> dict[str, Any]:
    start_ms = to_ms(AUDIT_START)
    end_ms = to_ms(AUDIT_END)
    indexes = [
        index
        for index, ts in enumerate(result.timestamps)
        if start_ms <= int(ts) < end_ms
    ]
    if not indexes:
        raise RuntimeError("2025 audit window is empty")
    timestamps = [result.timestamps[index] for index in indexes]
    equity = [result.equity[index] for index in indexes]
    fills = [fill for fill in result.fills if start_ms <= fill.ts < end_ms]
    opening = result.equity[indexes[0] - 1] if indexes[0] > 0 else INITIAL_CASH
    metrics = compute_metrics(timestamps, equity, fills, opening)
    episodes = episode_returns(timestamps, equity, fills, opening)
    bootstrap = bootstrap_trades(episodes, samples=SAMPLES, seed=SEED)
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


def _weighted_random_null(
    series: Series,
    spans: list[tuple[int, int | None]],
    observed: float,
    size: float,
    samples: int = SAMPLES,
    seed: int = SEED,
) -> dict[str, float | int]:
    """Match entry year and holding days for a fixed-weight spot position."""
    index_of = {int(ts): index for index, ts in enumerate(series.ts)}
    years = np.array([int(from_ms(int(ts))[:4]) for ts in series.ts], dtype=int)
    indexes = np.arange(len(series), dtype=int)
    rng = np.random.default_rng(seed)
    totals = np.ones(samples, dtype=float)
    fee = BASE_FEE_BPS / 10_000
    slip = BASE_SLIPPAGE_BPS / 10_000

    for entry_ts, exit_ts in spans:
        entry_index = index_of[int(entry_ts)]
        exit_index = len(series) - 1 if exit_ts is None else index_of[int(exit_ts)]
        holding_bars = exit_index - entry_index
        if holding_bars < 1:
            raise ValueError("matched episodes must hold at least one day")
        valid_end = indexes + holding_bars < len(series)
        candidates = indexes[(years == years[entry_index]) & valid_end]
        candidates = candidates[
            (series.volume[candidates] > 0)
            & (series.volume[candidates + holding_bars] > 0)
        ]
        if len(candidates) == 0:
            raise ValueError("no matched random entry candidates")
        starts = rng.choice(candidates, size=samples, replace=True)
        exits = starts + holding_bars
        gross_exit = (
            series.open[exits] / series.open[starts] * (1.0 - slip) * (1.0 - fee)
        )
        gross_entry = (1.0 + slip) * (1.0 + fee)
        totals *= 1.0 + size * (gross_exit - gross_entry)

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


def _gate(
    audit: dict[str, Any],
    stress: dict[str, Any],
    blocks: list[dict[str, float | int]],
    jackknife: list[dict[str, float | int]],
    random_null: dict[str, float | int],
) -> dict[str, Any]:
    checks = [
        ("2025 15 bps return > 0", audit["return"] > 0),
        ("2025 Sharpe >= 0.20", audit["sharpe"] >= 0.20),
        ("2025 MaxDD <= 20%", audit["max_drawdown"] <= 0.20),
        ("2025 25 bps/side return > 0", stress["return"] > 0),
        ("2025 return less best closed trade > 0", audit["return_less_best_1"] > 0),
        ("2025 at least four closed trades", audit["trades"] >= 4),
        (
            "pooled circular block-bootstrap P5 > 0 at sizes 2 and 4",
            all(float(row["p05"]) > 0 for row in blocks),
        ),
        (
            "every pooled entry-year jackknife return > 0",
            all(float(row["return"]) > 0 for row in jackknife),
        ),
        ("2025 matched-random one-sided p < 0.10", float(random_null["p_value"]) < 0.10),
    ]
    passed = all(bool(value) for _, value in checks)
    return {
        "passed": passed,
        "verdict": "PRE-FREEZE PASS" if passed else "PRE-FREEZE FAIL",
        "checks": [
            {"name": name, "passed": bool(value)} for name, value in checks
        ],
    }


def _pct(value: float) -> str:
    return f"{value * 100:+.2f}%"


def _render(payload: dict[str, Any]) -> str:
    audit = payload["audit_2025"]
    stress = payload["stress_25bps"]
    lines = [
        "# DOGE DVR-T20 2025 Pre-freeze 审计结果",
        "",
        "> 策略参数与通过2024验证的版本完全相同; 本报告是第一次打开2025。",
        "",
        f"**{payload['gate']['verdict']}**",
        "",
        "| Return | Sharpe | MaxDD | Trades | Less best 1 | 25bps return |",
        "|---:|---:|---:|---:|---:|---:|",
        (
            f"| {_pct(audit['return'])} | {audit['sharpe']:.2f} | "
            f"{_pct(-audit['max_drawdown'])} | {audit['trades']} | "
            f"{_pct(audit['return_less_best_1'])} | {_pct(stress['return'])} |"
        ),
        "",
        "## 审计门",
        "",
    ]
    lines.extend(
        f"- {'PASS' if check['passed'] else 'FAIL'} - {check['name']}"
        for check in payload["gate"]["checks"]
    )
    lines += [
        "",
        "## Pooled 2021-2025 block bootstrap",
        "",
        "| Block episodes | P5 | Median | P95 | P(loss) |",
        "|---:|---:|---:|---:|---:|",
    ]
    for row in payload["pooled_block_bootstrap"]:
        lines.append(
            f"| {row['block_size']} | {_pct(float(row['p05']))} | "
            f"{_pct(float(row['median']))} | {_pct(float(row['p95']))} | "
            f"{_pct(float(row['probability_of_loss']))} |"
        )
    null = payload["matched_random_2025"]
    lines += [
        "",
        "## 2025 匹配随机入场",
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
        f"- Bars loaded: {payload['bars']}",
        f"- Range loaded: `{payload['range']}`",
        "- Query hard end: `2026-01-01 00:00 UTC` (exclusive)",
        "- 2025 evaluation is cold-start; pooled robustness is explicitly in-sample",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    end_ms = to_ms(AUDIT_END)
    with Store(DB_PATH) as store:
        series = load_series(store, INSTRUMENT, TIMEFRAME, end_ms=end_ms)
    if len(series) == 0:
        raise SystemExit("DOGE-USDT pre-freeze data missing")
    if int(series.ts[-1]) >= end_ms:
        raise RuntimeError("2025 audit crossed the frozen 2026 boundary")

    audit_result = _run_window(series, BASE_SLIPPAGE_BPS)
    audit = _window_summary(audit_result)
    stress = _window_summary(_run_window(series, STRESS_SLIPPAGE_BPS))

    full_result = _run_full(series)
    pooled_episodes = episode_returns(
        full_result.timestamps,
        full_result.equity,
        full_result.fills,
        full_result.initial_cash,
    )
    pooled_spans = position_spans(full_result.fills)
    if len(pooled_episodes) != len(pooled_spans):
        raise RuntimeError("pooled episode returns and spans disagree")
    entry_years = [int(from_ms(entry_ts)[:4]) for entry_ts, _ in pooled_spans]
    blocks = [
        _block_bootstrap(pooled_episodes, size, samples=SAMPLES, seed=SEED + size)
        for size in (2, 4)
    ]
    jackknife = _year_jackknife(pooled_episodes, entry_years)

    audit_episodes = episode_returns(
        audit_result.timestamps,
        audit_result.equity,
        audit_result.fills,
        audit_result.initial_cash,
    )
    audit_spans = position_spans(audit_result.fills)
    if len(audit_episodes) != len(audit_spans):
        raise RuntimeError("2025 episode returns and spans disagree")
    observed = float(np.prod(1.0 + np.asarray(audit_episodes)) - 1.0)
    random_null = _weighted_random_null(
        series,
        audit_spans,
        observed,
        size=DogeDvrConfig().size,
    )
    gate = _gate(audit, stress, blocks, jackknife, random_null)

    payload: dict[str, Any] = {
        "study": "doge-dvr-tail20-v1",
        "stage": "2025_pre_freeze_audit",
        "accessed_at": dt.datetime.now(dt.UTC).isoformat(),
        "data_fingerprint": series_fingerprint(series),
        "strategy_source_sha256": hashlib.sha256(
            STRATEGY_SOURCE.read_bytes()
        ).hexdigest(),
        "bars": len(series),
        "range": f"{from_ms(int(series.ts[0]))}..{from_ms(int(series.ts[-1]))}",
        "audit_2025": audit,
        "stress_25bps": stress,
        "pooled_block_bootstrap": blocks,
        "pooled_year_jackknife": jackknife,
        "matched_random_2025": random_null,
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
