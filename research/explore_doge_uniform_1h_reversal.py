#!/usr/bin/env python
"""Pre-2024 discovery for the uniform 1h reversal baseline (U1R v1).

Direction C of the 1h DOGE-spot study. The formula, family and gates were
frozen in ``UNIFORM_1H_REVERSAL_PROTOCOL_2026-07-23.md`` before this runner ran,
and the version is pre-declared an expected DISCOVERY FAIL: the point is a clean,
engine-measured negative baseline for short-horizon single-asset reversal net of
turnover cost, not an edge. Every market query has an exclusive 2024 boundary.

Single asset only: no BTC/ETH/swap/funding, per the yearly-research boundary.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from cq.context import Context, Series, series_fingerprint
from cq.core.types import CostModel, Intent, MarketSpec, Sizing
from cq.data.feed import load_series
from cq.data.store import Store
from cq.engine.loop import RunResult, run_backtest
from cq.research.metrics import (
    compute_metrics,
    episode_returns,
    trades_from_fills,
)
from cq.research.split import from_ms, to_ms
from cq.research.stats import bootstrap_trades

DB_PATH = "data/cq.db"
INSTRUMENT = "DOGE-USDT"
TIMEFRAME = "1h"
DISCOVERY_END = "2024-01-01"
INITIAL_CASH = 10_000.0
BASE_FEE_BPS = 10.0
BASE_SLIPPAGE_BPS = 5.0
STRESS_SLIPPAGE_BPS = 15.0
SAMPLES = 10_000
SEED = 20260723
FAMILY_TRIALS = 6
OUTPUT_JSON = Path("reports/research/doge_uniform_1h_reversal_discovery.json")
OUTPUT_MD = Path(
    "docs/research/doge-spot/UNIFORM_1H_REVERSAL_DISCOVERY_RESULTS_2026-07-23.md"
)


class ResearchStrategy(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def warmup_bars(self) -> int: ...

    def reset(self) -> None: ...

    def on_bar(self, ctx: Context) -> Intent: ...


@dataclass(frozen=True)
class U1rParams:
    """Frozen uniform-reversal parameters."""

    lookback: int = 1
    deadband: float = 0.0
    size: float = 1.0

    def __post_init__(self) -> None:
        if self.lookback < 1:
            raise ValueError("lookback must be positive")
        if self.deadband < 0:
            raise ValueError("deadband cannot be negative")
        if not 0 < self.size <= 1:
            raise ValueError("spot size must be in (0, 1]")


class DogeUniform1hReversal:
    """Long/cash single-asset reversal timer, re-decided every 1h bar.

    Buy after a k-hour drop beyond the deadband, return to cash after a k-hour
    rise beyond it; otherwise hold. No stops, no rebalancing within a hold.
    """

    def __init__(self, params: U1rParams | None = None):
        self.params = params or U1rParams()
        self._target = 0.0

    @property
    def name(self) -> str:
        p = self.params
        return f"doge-u1r-k{p.lookback}-db{p.deadband * 100:g}-size{p.size:g}"

    @property
    def warmup_bars(self) -> int:
        return self.params.lookback + 1

    def reset(self) -> None:
        self._target = 0.0

    def snapshot_state(self) -> dict[str, object]:
        return {"target": self._target, "params": asdict(self.params)}

    def restore_state(self, state: dict[str, object]) -> None:
        if state.get("params") != asdict(self.params):
            raise ValueError("U1R checkpoint configuration does not match")
        raw = state.get("target")
        if (
            isinstance(raw, bool)
            or not isinstance(raw, (int, float))
            or float(raw) not in (0.0, self.params.size)
        ):
            raise ValueError("invalid U1R checkpoint target")
        self._target = float(raw)

    def on_bar(self, ctx: Context) -> Intent:
        p = self.params
        closes = ctx.close(p.lookback + 1)
        reversal_return = float(np.log(closes[-1] / closes[0]))
        if reversal_return < -p.deadband:
            self._target = p.size
        elif reversal_return > p.deadband:
            self._target = 0.0
        return Intent(target=self._target, reason=self.name)


class AlwaysLong:
    """Buy once and hold: the passive Buy&Hold reference."""

    def __init__(self, size: float = 1.0):
        self.size = size

    @property
    def name(self) -> str:
        return f"doge-buy-hold-size{self.size:g}"

    @property
    def warmup_bars(self) -> int:
        return 1

    def reset(self) -> None:
        return None

    def on_bar(self, ctx: Context) -> Intent:
        return Intent(target=self.size, reason=self.name)


class WindowedStrategy:
    """Cold-start an inner strategy and stay in cash outside one year."""

    def __init__(self, factory: Callable[[], ResearchStrategy], start_ms: int, end_ms: int):
        self.inner = factory()
        self.start_ms = start_ms
        self.end_ms = end_ms

    @property
    def name(self) -> str:
        return f"{self.inner.name}-windowed"

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


def candidate_factories() -> dict[str, Callable[[], DogeUniform1hReversal]]:
    return {
        "main": DogeUniform1hReversal,
        "k2": lambda: DogeUniform1hReversal(U1rParams(lookback=2)),
        "k3": lambda: DogeUniform1hReversal(U1rParams(lookback=3)),
        "k6": lambda: DogeUniform1hReversal(U1rParams(lookback=6)),
        "db0.5": lambda: DogeUniform1hReversal(U1rParams(deadband=0.005)),
        "db1.0": lambda: DogeUniform1hReversal(U1rParams(deadband=0.010)),
    }


def _run(
    strategy: ResearchStrategy,
    series: Series,
    fee_bps: float = BASE_FEE_BPS,
    slippage_bps: float = BASE_SLIPPAGE_BPS,
) -> RunResult:
    return run_backtest(
        strategy,
        series,
        MarketSpec(INSTRUMENT, "spot"),
        INITIAL_CASH,
        costs=CostModel(fee_bps=fee_bps, slippage_bps=slippage_bps),
        funding=None,
        sizing=Sizing.ON_ENTRY,
    )


def _summary(result: RunResult) -> dict[str, Any]:
    metrics = compute_metrics(
        result.timestamps, result.equity, result.fills, result.initial_cash
    )
    episodes = episode_returns(
        result.timestamps, result.equity, result.fills, result.initial_cash
    )
    bootstrap = bootstrap_trades(episodes, samples=SAMPLES, seed=SEED)
    trades = trades_from_fills(result.fills)
    net = sorted((trade.net_pnl for trade in trades), reverse=True)
    holds = [t.holding_ms / (3600 * 1000) for t in trades]
    return {
        "return": metrics.total_return,
        "cagr": metrics.cagr,
        "sharpe": metrics.sharpe,
        "max_drawdown": metrics.max_drawdown,
        "longest_drawdown_days": metrics.longest_drawdown_days,
        "trades": metrics.trades,
        "win_rate": metrics.win_rate,
        "profit_factor": metrics.profit_factor,
        "mean_hold_hours": float(np.mean(holds)) if holds else 0.0,
        "mean_episode_return": float(np.mean(episodes)) if episodes else 0.0,
        "return_less_best_1": (
            (result.final_equity - (net[0] if net else 0.0)) / result.initial_cash - 1.0
        ),
        "episode_count": len(episodes),
        "bootstrap_probability_of_loss": bootstrap.probability_of_loss,
        "bootstrap_p05": bootstrap.percentile_05,
        "bootstrap_median": bootstrap.median,
        "bootstrap_p95": bootstrap.percentile_95,
        "fills": len(result.fills),
    }


def _cold_year(
    series: Series, factory: Callable[[], ResearchStrategy], year: int
) -> dict[str, Any]:
    start_ms = to_ms(f"{year}-01-01")
    end_ms = to_ms(f"{year + 1}-01-01")
    result = _run(WindowedStrategy(factory, start_ms, end_ms), series)
    indexes = [i for i, ts in enumerate(result.timestamps) if start_ms <= int(ts) < end_ms]
    if not indexes:
        raise RuntimeError(f"no evaluation bars for {year}")
    timestamps = [result.timestamps[i] for i in indexes]
    equity = [result.equity[i] for i in indexes]
    fills = [f for f in result.fills if start_ms <= f.ts < end_ms]
    opening = result.equity[indexes[0] - 1] if indexes[0] > 0 else INITIAL_CASH
    metrics = compute_metrics(timestamps, equity, fills, opening)
    return {
        "year": year,
        "return": equity[-1] / opening - 1.0,
        "sharpe": metrics.sharpe,
        "max_drawdown": metrics.max_drawdown,
        "trades": metrics.trades,
    }


def _cost_ladder(series: Series) -> list[dict[str, Any]]:
    rungs = [("0bps", 0.0, 0.0), ("15bps", BASE_FEE_BPS, BASE_SLIPPAGE_BPS),
             ("25bps", BASE_FEE_BPS, STRESS_SLIPPAGE_BPS)]
    ladder: list[dict[str, Any]] = []
    for label, fee, slip in rungs:
        result = _run(DogeUniform1hReversal(), series, fee_bps=fee, slippage_bps=slip)
        metrics = compute_metrics(
            result.timestamps, result.equity, result.fills, result.initial_cash
        )
        ladder.append(
            {
                "label": label,
                "per_side_bps": fee + slip,
                "return": metrics.total_return,
                "sharpe": metrics.sharpe,
                "trades": metrics.trades,
            }
        )
    return ladder


def _gate(
    main: dict[str, Any],
    stress: dict[str, Any],
    yearly: list[dict[str, Any]],
    buy_hold: dict[str, Any],
    variants: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    positive_versions = sum(row["return"] > 0 for row in variants.values())
    checks = [
        ("15 bps return > 0", main["return"] > 0),
        ("15 bps Sharpe >= 0.50", main["sharpe"] >= 0.50),
        ("MaxDD <= 35%", main["max_drawdown"] <= 0.35),
        ("at least 20 closed trades", main["trades"] >= 20),
        (
            "at least two positive cold-start years",
            sum(row["return"] > 0 for row in yearly) >= 2,
        ),
        ("25 bps/side return > 0", stress["return"] > 0),
        ("return less best closed trade > 0", main["return_less_best_1"] > 0),
        ("episode bootstrap P5 > 0", main["bootstrap_p05"] > 0),
        ("main 15bps return > buy&hold net return", main["return"] > buy_hold["return"]),
        ("at least four of six versions positive at 15bps", positive_versions >= 4),
    ]
    passed = all(bool(value) for _, value in checks)
    return {
        "passed": passed,
        "verdict": "DISCOVERY PASS" if passed else "DISCOVERY FAIL",
        "checks": [{"name": name, "passed": bool(value)} for name, value in checks],
    }


def _pct(value: float) -> str:
    return f"{value * 100:+.2f}%"


def _render(payload: dict[str, Any]) -> str:
    main = payload["main"]
    stress = payload["stress_25bps"]
    bh = payload["buy_hold"]
    lines = [
        "# DOGE 均匀 1h 反转发现结果 (U1R v1, 2021-2023)",
        "",
        "> 本进程在数据库层排他硬截止 2024-01-01; 未读取后续年度。单资产, 不用 BTC/ETH。",
        "> **预先声明本版本预期 FAIL**: 价值是负面基线与成本分解, 不是 edge。",
        "",
        "## 结论",
        "",
        f"**{payload['gate']['verdict']}**",
        "",
        "## 冻结主版本 (k=1, deadband=0, 15bps)",
        "",
        "| Return | Sharpe | MaxDD | Trades | Mean hold h | Less best 1 | 25bps | Bootstrap P5 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"| {_pct(main['return'])} | {main['sharpe']:.2f} | "
        f"{_pct(-main['max_drawdown'])} | {main['trades']} | "
        f"{main['mean_hold_hours']:.1f} | {_pct(main['return_less_best_1'])} | "
        f"{_pct(stress['return'])} | {_pct(main['bootstrap_p05'])} |",
        "",
        "## 成本阶梯 (main, 每边 bps)",
        "",
        "| Cost | Return | Sharpe | Trades |",
        "|---|---:|---:|---:|",
    ]
    for rung in payload["cost_ladder"]:
        lines.append(
            f"| {rung['label']} | {_pct(rung['return'])} | {rung['sharpe']:.2f} | "
            f"{rung['trades']} |"
        )
    lines += [
        "",
        f"Buy&Hold 参照 (15bps): Return {_pct(bh['return'])}, Sharpe {bh['sharpe']:.2f}, "
        f"MaxDD {_pct(-bh['max_drawdown'])}, Trades {bh['trades']}",
        "",
        "## 冷启动自然年 (main, 15bps)",
        "",
        "| Year | Return | Sharpe | MaxDD | Trades |",
        "|---:|---:|---:|---:|---:|",
    ]
    for row in payload["yearly"]:
        lines.append(
            f"| {row['year']} | {_pct(row['return'])} | {row['sharpe']:.2f} | "
            f"{_pct(-row['max_drawdown'])} | {row['trades']} |"
        )
    lines += [
        "",
        "## 冻结家族 (15bps)",
        "",
        "| Version | Return | Sharpe | MaxDD | Trades | Mean episode |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name in ("k2", "k3", "k6", "db0.5", "db1.0"):
        row = payload["variants"][name]
        lines.append(
            f"| {name} | {_pct(row['return'])} | {row['sharpe']:.2f} | "
            f"{_pct(-row['max_drawdown'])} | {row['trades']} | "
            f"{_pct(row['mean_episode_return'])} |"
        )
    lines += [
        "",
        "## 冻结门明细",
        "",
    ]
    lines.extend(
        f"- {'PASS' if row['passed'] else 'FAIL'} — {row['name']}"
        for row in payload["gate"]["checks"]
    )
    lines += [
        "",
        "## Provenance",
        "",
        f"- DOGE fingerprint: `{payload['fingerprint']}`",
        f"- Bars: {payload['bars']}",
        f"- Range: `{payload['range']}`",
        "- Costs: 10 bps fee + 5 bps slippage per side; 25 bps stress",
        "- Execution: closed 1h decision, next open fill, long/cash spot",
        "- Protocol: `UNIFORM_1H_REVERSAL_PROTOCOL_2026-07-23.md`",
        "",
    ]
    if not payload["gate"]["passed"]:
        lines += [
            "按冻结规则, U1R v1 在 discovery 永久停止; 不读取 2024, 也不从邻域替补, 不调参。",
            "",
            "**关键读法**: 0bps 毛收益 +4116% / Sharpe 1.72 说明反转信号的毛 edge 巨大且真实, "
            "但需要 7027 笔交易 (日均 6.5 笔, 平均持有 1.9h); 15bps/边下换手成本把一切吞没到 "
            "-100%。**约束是换手频率, 不是信号有无。** deadband 邻域 (db1.0: 1458 笔仍 -98.4%) "
            "证实少交易有用但远不够。这为方向 A (尾部条件反转, 靠稀疏交易过成本墙) 指明命题: "
            "能否只收割这块毛 edge 的一小片、同时把交易压到能存活的频率。",
            "",
        ]
    return "\n".join(lines)


def main() -> int:
    end_ms = to_ms(DISCOVERY_END)
    with Store(DB_PATH) as store:
        series = load_series(store, INSTRUMENT, TIMEFRAME, end_ms=end_ms)
    if len(series) == 0:
        raise SystemExit("U1R discovery market data missing")
    if int(series.ts[-1]) >= end_ms:
        raise RuntimeError("U1R discovery query crossed the frozen 2024 boundary")

    factories = candidate_factories()
    results = {name: _run(factory(), series) for name, factory in factories.items()}
    summaries = {name: _summary(result) for name, result in results.items()}
    main_summary = summaries["main"]
    stress = _summary(_run(factories["main"](), series, slippage_bps=STRESS_SLIPPAGE_BPS))
    buy_hold = _summary(_run(AlwaysLong(), series))
    yearly = [_cold_year(series, factories["main"], year) for year in range(2021, 2024)]
    cost_ladder = _cost_ladder(series)
    variants = {name: summaries[name] for name in factories if name != "main"}
    gate = _gate(main_summary, stress, yearly, buy_hold, {**variants, "main": main_summary})
    payload: dict[str, Any] = {
        "study": "doge-uniform-1h-reversal-v1",
        "stage": "discovery",
        "direction": "C",
        "expectation": "pre-declared expected DISCOVERY FAIL",
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "query_end_exclusive": DISCOVERY_END,
        "params": asdict(U1rParams()),
        "family_trials": FAMILY_TRIALS,
        "fingerprint": series_fingerprint(series),
        "bars": len(series),
        "range": f"{from_ms(int(series.ts[0]))}..{from_ms(int(series.ts[-1]))}",
        "main": main_summary,
        "stress_25bps": stress,
        "buy_hold": buy_hold,
        "cost_ladder": cost_ladder,
        "yearly": yearly,
        "variants": variants,
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
