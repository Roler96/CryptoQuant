#!/usr/bin/env python
"""Temporal split and cold-start yearly reports for the frozen DOGE VCSE v1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cq.context import Context, Series, series_fingerprint
from cq.core.types import CostModel, Intent, MarketSpec, Sizing
from cq.data.feed import load_series
from cq.data.store import Store
from cq.engine.loop import RunResult, run_backtest
from cq.research.metrics import compute_metrics, episode_returns, trades_from_fills
from cq.research.split import (
    Segment,
    SplitPlan,
    holdout_access_count,
    record_holdout_access,
    to_ms,
)
from cq.research.stats import bootstrap_trades
from research.backtest_doge_vcse import (
    BASE_FEE_BPS,
    BASE_SLIPPAGE_BPS,
    DB_PATH,
    INITIAL_CASH,
    INSTRUMENT,
    TIMEFRAME,
    DogeVcse,
    VcseParams,
    _run,
    _summary,
)

DEVELOPMENT_START = "2021-01-01"
HOLDOUT_START = "2026-01-01"
OUTPUT_DIR = Path("docs/research/doge-spot/yearly")
OUTPUT_JSON = Path("reports/research/doge_vcse_temporal_split.json")
OUTPUT_AGGREGATE = Path("docs/research/doge-spot/VCSE_TEMPORAL_SPLIT_2026.md")
STUDY = "doge-vcse-v1-2026-temporal-holdout"


class WindowedVcse:
    """Keep cash outside one evaluation window while preserving causal warmup."""

    def __init__(self, start_ms: int, end_ms: int | None, params: VcseParams | None = None):
        self.inner = DogeVcse(params)
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
        decision = ctx.decision_time
        if decision < self.start_ms:
            return Intent(target=0.0, reason=f"{self.name}-before-window")
        if self.end_ms is not None and decision >= self.end_ms:
            return Intent(target=0.0, reason=f"{self.name}-after-window")
        return self.inner.on_bar(ctx)


def _window_run(series: Series, start: str, end: str | None) -> RunResult:
    return run_backtest(
        WindowedVcse(to_ms(start), to_ms(end) if end else None),
        series,
        MarketSpec(INSTRUMENT, "spot"),
        INITIAL_CASH,
        costs=CostModel(fee_bps=BASE_FEE_BPS, slippage_bps=BASE_SLIPPAGE_BPS),
        sizing=Sizing.ON_ENTRY,
    )


def _window_summary(
    result: RunResult, start: str, end: str | None, last_data_ms: int
) -> dict[str, Any]:
    start_ms = to_ms(start)
    end_ms = to_ms(end) if end else last_data_ms + 4 * 60 * 60 * 1000
    indexes = [
        index
        for index, ts in enumerate(result.timestamps)
        if start_ms <= int(ts) < end_ms
    ]
    if not indexes:
        raise ValueError(f"no bars in evaluation window {start}..{end or 'latest'}")
    timestamps = [result.timestamps[index] for index in indexes]
    equity = [result.equity[index] for index in indexes]
    fills = [fill for fill in result.fills if start_ms <= fill.ts < end_ms]
    opening_equity = (
        result.equity[indexes[0] - 1] if indexes[0] > 0 else result.initial_cash
    )
    metrics = compute_metrics(timestamps, equity, fills, opening_equity)
    episodes = episode_returns(timestamps, equity, fills, opening_equity)
    bootstrap = bootstrap_trades(episodes, samples=10_000, seed=20260722)
    trades = trades_from_fills(fills)
    net = sorted((trade.net_pnl for trade in trades), reverse=True)
    marked_return = equity[-1] / opening_equity - 1.0

    return {
        "start": start,
        "end": end or "latest",
        "bars": len(timestamps),
        "return": marked_return,
        "cagr": metrics.cagr,
        "sharpe": metrics.sharpe,
        "max_drawdown": metrics.max_drawdown,
        "longest_drawdown_days": metrics.longest_drawdown_days,
        "closed_trades": len(trades),
        "fills": len(fills),
        "win_rate": metrics.win_rate,
        "profit_factor": metrics.profit_factor,
        "open_position_at_end": len(fills) % 2 == 1,
        "return_less_best_1": (
            (equity[-1] - (net[0] if net else 0.0)) / opening_equity - 1.0
        ),
        "bootstrap_probability_of_loss": bootstrap.probability_of_loss,
        "bootstrap_p05": bootstrap.percentile_05,
        "bootstrap_median": bootstrap.median,
        "bootstrap_p95": bootstrap.percentile_95,
    }


def _pct(value: float) -> str:
    return f"{value * 100:+.2f}%"


def _render_one(label: str, row: dict[str, Any], fingerprint: str) -> str:
    return "\n".join(
        [
            f"# DOGE VCSE - {label}",
            "",
            "| Metric | Result |",
            "|---|---:|",
            f"| Window | `{row['start']}..{row['end']}` |",
            f"| Bars | {row['bars']} |",
            f"| Return | **{_pct(row['return'])}** |",
            f"| CAGR | {_pct(row['cagr'])} |",
            f"| Sharpe | {row['sharpe']:.2f} |",
            f"| MaxDD | {_pct(-row['max_drawdown'])} |",
            f"| Closed trades | {row['closed_trades']} |",
            f"| Win rate | {_pct(row['win_rate'])} |",
            f"| Profit factor | {row['profit_factor']:.2f} |",
            f"| Return less best closed trade | {_pct(row['return_less_best_1'])} |",
            f"| Bootstrap P5 | {_pct(row['bootstrap_p05'])} |",
            f"| Bootstrap loss probability | {_pct(row['bootstrap_probability_of_loss'])} |",
            f"| Open position at end | {row['open_position_at_end']} |",
            "",
            "## Provenance",
            "",
            f"- Data fingerprint: `{fingerprint}`",
            "- Input: DOGE-USDT spot OHLCV only",
            "- Cold start: cash before window; prior DOGE bars visible only as indicator warmup",
            "- Execution: decision on closed 4h bar, fill at next 4h open",
            "- Costs: 10 bps fee + 5 bps slippage per side",
            "",
        ]
    )


def _render_aggregate(payload: dict[str, Any]) -> str:
    development = payload["development"]
    holdout = payload["holdout_2026"]
    yearly = payload["yearly"]
    lines = [
        "# DOGE VCSE - 2021-2025开发集与2026时间冻结样本",
        "",
        "> 2026已在VCSE v1全历史报告中被访问, 因此本报告称temporal holdout, "
        "不称pristine OOS。",
        "",
        "## 汇总",
        "",
        "| Segment | Return | Sharpe | MaxDD | Closed trades | Bootstrap P5 |",
        "|---|---:|---:|---:|---:|---:|",
        (
            f"| 2021-2025 development | {_pct(development['return'])} | "
            f"{development['sharpe']:.2f} | {_pct(-development['max_drawdown'])} | "
            f"{development['trades']} | {_pct(development['bootstrap_p05'])} |"
        ),
        (
            f"| 2026 temporal holdout | {_pct(holdout['return'])} | "
            f"{holdout['sharpe']:.2f} | {_pct(-holdout['max_drawdown'])} | "
            f"{holdout['closed_trades']} | {_pct(holdout['bootstrap_p05'])} |"
        ),
        "",
        "## 冷启动逐年结果",
        "",
        "| Year | Return | Sharpe | MaxDD | Closed trades | PF |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for year, row in yearly.items():
        lines.append(
            f"| {year} | {_pct(row['return'])} | {row['sharpe']:.2f} | "
            f"{_pct(-row['max_drawdown'])} | {row['closed_trades']} | "
            f"{row['profit_factor']:.2f} |"
        )
    lines += [
        "",
        "## 口径",
        "",
        "- 开发回测只加载2026-01-01以前的数据。",
        "- 2026报告读取2021-2025 DOGE数据作为指标warmup, 但2026以前始终持有现金。",
        "- 每个年度报告单独冷启动, 不继承上一年的仓位或复利权益。",
        "- 所有信号仍只使用DOGE-USDT现货OHLCV。",
        f"- Data fingerprint: `{payload['data_fingerprint']}`",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    with Store(DB_PATH) as store:
        full = load_series(store, INSTRUMENT, TIMEFRAME)
        development_series = load_series(
            store, INSTRUMENT, TIMEFRAME, end_ms=to_ms(HOLDOUT_START)
        )
    if len(full) == 0 or len(development_series) == 0:
        raise SystemExit("DOGE-USDT data missing")

    split = SplitPlan(
        study=STUDY,
        segments=(
            Segment("development", DEVELOPMENT_START, HOLDOUT_START, role="explore"),
            Segment("temporal_holdout", HOLDOUT_START, "2027-01-01", role="holdout"),
        ),
        freeze_point=HOLDOUT_START,
    )
    if holdout_access_count(STUDY) == 0:
        record_holdout_access(
            study=STUDY,
            segment="temporal_holdout",
            hypothesis=(
                "Frozen VCSE v1 remains profitable in 2026 after 15 bps/side, "
                "without changing any rule selected on the 2021-2025 development period"
            ),
            fingerprint=split.fingerprint,
        )

    development = _summary(_run(development_series, VcseParams()))
    last_data_ms = int(full.ts[-1])
    holdout_result = _window_run(full, HOLDOUT_START, None)
    holdout = _window_summary(holdout_result, HOLDOUT_START, None, last_data_ms)

    yearly: dict[str, dict[str, Any]] = {}
    for year in range(2021, 2027):
        start = f"{year}-01-01"
        end = f"{year + 1}-01-01" if year < 2026 else None
        result = _window_run(full, start, end)
        yearly[str(year)] = _window_summary(result, start, end, last_data_ms)

    payload = {
        "study": STUDY,
        "split_fingerprint": split.fingerprint,
        "data_fingerprint": series_fingerprint(full),
        "development": development,
        "holdout_2026": holdout,
        "yearly": yearly,
    }
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    for year, row in yearly.items():
        (OUTPUT_DIR / f"VCSE_{year}.md").write_text(
            _render_one(year, row, payload["data_fingerprint"]), encoding="utf-8"
        )
    OUTPUT_AGGREGATE.write_text(_render_aggregate(payload), encoding="utf-8")
    print(_render_aggregate(payload))
    print(f"JSON: {OUTPUT_JSON}")
    print(f"AGGREGATE: {OUTPUT_AGGREGATE}")
    print(f"YEARLY: {OUTPUT_DIR}/VCSE_2021.md .. VCSE_2026.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
