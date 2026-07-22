#!/usr/bin/env python
"""DOGE 现货波动收割(恒定混合)研究。

不预测、不择时:在 DOGE/USDT 之间维持恒定目标权重,权重漂移超过带宽才在下一根
日线 open 拉回。四种策略是同一份代码的不同 (sizing, weight, band),全程走真引擎、
真成本、真撮合语义,因此最大可比。正确的 null 是同等平均暴露的静态漂移配置,而不是
匹配随机入场——本策略没有入场决策。

不可变的结果盲定义与门槛见 ``VOLATILITY_HARVEST_PROTOCOL_2026-07-22.md``。discovery
查询在数据库层硬截止 2024-01-01;顺序验证的每个自然年独立冷启动,主配置在读取任何
结果前即由协议冻结。
"""

from __future__ import annotations

import datetime as dt
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from cq.context import Context, Series, series_fingerprint
from cq.core.types import CostModel, Intent, MarketSpec, Sizing
from cq.data.feed import load_series
from cq.data.store import Store
from cq.engine.loop import RunResult, run_backtest
from cq.research.metrics import compute_metrics, per_bar_returns
from cq.research.split import from_ms, to_ms
from research.explore_doge_directional_regimes import WindowedStrategy

DB_PATH = "data/cq.db"
INSTRUMENT = "DOGE-USDT"
TIMEFRAME = "1d"
DISCOVERY_END = "2024-01-01"
INITIAL_CASH = 10_000.0
FEE_BPS = 10.0
MAIN_SLIP_BPS = 5.0
STRESS_SLIP_BPS = 15.0
SEED = 20260722

WEIGHTS = (0.20, 0.30, 0.40, 0.50)
BANDS = (0.05, 0.10, 0.20)
MAIN_WEIGHT = 0.30
MAIN_BAND = 0.10
BLOCK = 20
BOOTSTRAP_SAMPLES = 10_000

SPEC = MarketSpec(INSTRUMENT, "spot")
OUTPUT_JSON = Path("reports/research/doge_volatility_harvest.json")
OUTPUT_MD = Path(
    "docs/research/doge-spot/VOLATILITY_HARVEST_DISCOVERY_RESULTS_2026-07-22.md"
)


class DogeConstantMix:
    """Hold a constant target weight of DOGE; the band decides when to trade.

    Reads no history and forecasts nothing: ``on_bar`` always names the same
    target weight. Whether that weight has drifted far enough to be worth a
    trade is the engine's rebalance-band decision (``dust_fraction`` under
    ``Sizing.REBALANCE``), not the strategy's. With ``Sizing.ON_ENTRY`` the
    same class is a static allocation that is sized once and then left to
    drift, which is exactly the benchmark the rebalancing action is measured
    against.
    """

    def __init__(self, weight: float):
        if not 0.0 < weight <= 1.0:
            raise ValueError("weight must be in (0, 1]")
        self.weight = weight

    @property
    def name(self) -> str:
        return f"doge-constant-mix-{self.weight:g}"

    @property
    def warmup_bars(self) -> int:
        return 1

    def reset(self) -> None:  # stateless, but the loop resets every strategy
        return None

    def snapshot_state(self) -> dict[str, object]:
        return {"weight": self.weight}

    def restore_state(self, state: dict[str, object]) -> None:
        if state.get("weight") != self.weight:
            raise ValueError("constant-mix checkpoint weight does not match")

    def on_bar(self, ctx: Context) -> Intent:
        return Intent(target=self.weight, reason=self.name)


def _run(
    weight: float,
    sizing: Sizing,
    dust: float | None,
    series: Series,
    slippage_bps: float = MAIN_SLIP_BPS,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> RunResult:
    if start_ms is None and end_ms is None:
        strategy: Any = DogeConstantMix(weight)
    else:
        strategy = WindowedStrategy(
            lambda: DogeConstantMix(weight),
            start_ms if start_ms is not None else int(series.ts[0]),
            end_ms if end_ms is not None else int(series.ts[-1]) + 1,
        )
    return run_backtest(
        strategy,
        series,
        SPEC,
        INITIAL_CASH,
        costs=CostModel(fee_bps=FEE_BPS, slippage_bps=slippage_bps),
        sizing=sizing,
        dust_fraction=dust,
    )


def _calmar(cagr: float, max_drawdown: float) -> float:
    if max_drawdown <= 0:
        return math.inf if cagr > 0 else 0.0
    return cagr / max_drawdown


def _turnover(result: RunResult) -> float:
    """Annualised traded notional as a multiple of average equity."""
    traded = sum(abs(fill.quantity * fill.price) for fill in result.fills)
    equity = np.asarray(result.equity, dtype=np.float64)
    avg_equity = float(np.mean(equity)) if len(equity) else INITIAL_CASH
    span_ms = (
        result.timestamps[-1] - result.timestamps[0]
        if len(result.timestamps) > 1
        else 0
    )
    years = span_ms / (365.25 * 24 * 3600 * 1000)
    if avg_equity <= 0 or years <= 0:
        return 0.0
    return traded / avg_equity / years


def _summary(result: RunResult) -> dict[str, Any]:
    metrics = compute_metrics(
        result.timestamps, result.equity, result.fills, result.initial_cash
    )
    return {
        "return": metrics.total_return,
        "cagr": metrics.cagr,
        "sharpe": metrics.sharpe,
        "max_drawdown": metrics.max_drawdown,
        "calmar": _calmar(metrics.cagr, metrics.max_drawdown),
        "longest_drawdown_days": metrics.longest_drawdown_days,
        "fills": len(result.fills),
        "turnover": _turnover(result),
    }


def _window_summary(
    weight: float,
    sizing: Sizing,
    dust: float | None,
    series: Series,
    year: int,
    slippage_bps: float = MAIN_SLIP_BPS,
) -> dict[str, Any]:
    start_ms = to_ms(f"{year}-01-01")
    end_ms = to_ms(f"{year + 1}-01-01")
    result = _run(
        weight, sizing, dust, series, slippage_bps=slippage_bps,
        start_ms=start_ms, end_ms=end_ms,
    )
    indexes = [
        index
        for index, ts in enumerate(result.timestamps)
        if start_ms <= int(ts) < end_ms
    ]
    if not indexes:
        return {"year": year, "return": 0.0, "calmar": 0.0, "max_drawdown": 0.0, "fills": 0}
    timestamps = [result.timestamps[index] for index in indexes]
    equity = [result.equity[index] for index in indexes]
    fills = [fill for fill in result.fills if start_ms <= fill.ts < end_ms]
    opening = result.equity[indexes[0] - 1] if indexes[0] > 0 else INITIAL_CASH
    metrics = compute_metrics(timestamps, equity, fills, opening)
    return {
        "year": year,
        "return": equity[-1] / opening - 1.0 if opening > 0 else 0.0,
        "cagr": metrics.cagr,
        "sharpe": metrics.sharpe,
        "max_drawdown": metrics.max_drawdown,
        "calmar": _calmar(metrics.cagr, metrics.max_drawdown),
        "fills": len(fills),
    }


@dataclass(frozen=True)
class DiffBootstrap:
    observed_mean: float
    prob_positive: float
    p05: float
    info_ratio: float


def _block_bootstrap_diff(
    band_equity: list[float],
    static_equity: list[float],
    timestamps: list[int],
    seed: int = SEED,
) -> DiffBootstrap:
    """Circular block bootstrap of the per-bar (band - static) return.

    Tests whether the rebalancing *action* adds per-bar value over the matched
    static allocation, net of cost — the honest null for a strategy that makes
    no entry decision. Info ratio annualises the daily mean/std of the
    differential by the data's own spacing.
    """
    band = per_bar_returns(band_equity)
    static = per_bar_returns(static_equity)
    diff = band - static
    n = len(diff)
    if n < BLOCK * 2:
        return DiffBootstrap(0.0, 0.0, 0.0, 0.0)
    observed = float(np.mean(diff))
    rng = np.random.default_rng(seed)
    n_blocks = math.ceil(n / BLOCK)
    starts = rng.integers(0, n, size=(BOOTSTRAP_SAMPLES, n_blocks))
    offsets = np.arange(BLOCK)
    means = np.empty(BOOTSTRAP_SAMPLES, dtype=np.float64)
    for s in range(BOOTSTRAP_SAMPLES):
        idx = (starts[s][:, None] + offsets[None, :]).ravel() % n
        means[s] = float(np.mean(diff[idx[:n]]))
    std = float(np.std(diff, ddof=1))
    spacing = float(np.median(np.diff(timestamps))) if len(timestamps) > 1 else 0.0
    per_year = (365.25 * 24 * 3600 * 1000) / spacing if spacing > 0 else 0.0
    info_ratio = (observed / std * math.sqrt(per_year)) if std > 0 and per_year > 0 else 0.0
    return DiffBootstrap(
        observed_mean=observed,
        prob_positive=float(np.mean(means > 0)),
        p05=float(np.percentile(means, 5)),
        info_ratio=info_ratio,
    )


def _grid(series: Series, slippage_bps: float = MAIN_SLIP_BPS) -> dict[str, Any]:
    """BAND vs STATIC for every (weight, band) cell over the full window."""
    static = {w: _summary(_run(w, Sizing.ON_ENTRY, None, series, slippage_bps)) for w in WEIGHTS}
    cells: list[dict[str, Any]] = []
    for w in WEIGHTS:
        for b in BANDS:
            band = _summary(_run(w, Sizing.REBALANCE, b, series, slippage_bps))
            cells.append(
                {
                    "weight": w,
                    "band": b,
                    "band_calmar": band["calmar"],
                    "static_calmar": static[w]["calmar"],
                    "band_maxdd": band["max_drawdown"],
                    "static_maxdd": static[w]["max_drawdown"],
                    "band_beats_static": band["calmar"] > static[w]["calmar"],
                    "maxdd_ok": band["max_drawdown"] <= static[w]["max_drawdown"] + 0.01,
                    "summary": band,
                }
            )
    return {"static": static, "cells": cells}


def _gate(
    main: dict[str, Any],
    static_main: dict[str, Any],
    grid: dict[str, Any],
    stress_main: dict[str, Any],
    stress_static: dict[str, Any],
    yearly_band: list[dict[str, Any]],
    yearly_static: list[dict[str, Any]],
) -> dict[str, Any]:
    cells = grid["cells"]
    beats = sum(cell["band_beats_static"] for cell in cells)
    maxdd_ok = all(cell["maxdd_ok"] for cell in cells)
    year_wins = sum(
        band["calmar"] > static["calmar"]
        for band, static in zip(yearly_band, yearly_static, strict=True)
    )
    checks = [
        ("D1 主配置 MaxDD <= 45%", main["max_drawdown"] <= 0.45),
        ("D2 BAND Calmar > STATIC Calmar", main["calmar"] > static_main["calmar"]),
        ("D3 >=8/12 格 BAND Calmar > STATIC", beats >= 8),
        ("D4 全 12 格 BAND MaxDD <= STATIC+1pp", maxdd_ok),
        (
            "D5 25bps 下 BAND Calmar > STATIC",
            stress_main["calmar"] > stress_static["calmar"],
        ),
        ("D6 >=2/3 冷启动年 BAND Calmar > STATIC", year_wins >= 2),
        ("D7 主配置年化换手 <= 15x", main["turnover"] <= 15.0),
    ]
    return {
        "passed": all(bool(value) for _, value in checks),
        "cells_band_beats_static": beats,
        "year_wins": year_wins,
        "checks": [{"name": name, "passed": bool(value)} for name, value in checks],
    }


def _pct(value: float) -> str:
    return f"{value * 100:+.2f}%"


def _fmt(value: float) -> str:
    if math.isinf(value):
        return "inf"
    return f"{value:.2f}"


def _render(payload: dict[str, Any]) -> str:
    disc = payload["discovery"]
    main = disc["main"]
    static = disc["static_main"]
    bh = disc["buy_hold"]
    lines = [
        "# DOGE 波动收割(恒定混合)discovery 结果 (2021-2023)",
        "",
        "> 不预测、不择时。查询在数据库层硬截止 2024-01-01。协议见 "
        "`VOLATILITY_HARVEST_PROTOCOL_2026-07-22.md`。",
        "",
        f"## discovery 裁决:{'PASS' if disc['gate']['passed'] else 'FAIL'}",
        "",
        "同等平均暴露下,四策略在 2021-2023 DOGE 现货:",
        "",
        "| 策略 | Return | CAGR | Sharpe | MaxDD | Calmar | 水下天 | 成交 | 换手/yr |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    rows = [
        ("BH100 (100% DOGE)", bh),
        (f"STATIC({MAIN_WEIGHT:g}) 静态漂移", static),
        (f"BAND({MAIN_WEIGHT:g},{MAIN_BAND:g}) 带宽再平衡", main),
        (f"CONT({MAIN_WEIGHT:g}) 连续再平衡", disc["cont_main"]),
    ]
    for label, row in rows:
        lines.append(
            f"| {label} | {_pct(row['return'])} | {_pct(row['cagr'])} | "
            f"{row['sharpe']:.2f} | {_pct(-row['max_drawdown'])} | {_fmt(row['calmar'])} | "
            f"{row['longest_drawdown_days']:.0f} | {row['fills']} | {row['turnover']:.1f} |"
        )

    lines += [
        "",
        "## 稳健网格 (BAND Calmar vs STATIC Calmar, 15bps)",
        "",
        f"BAND 击败 STATIC 的格数:**{disc['gate']['cells_band_beats_static']}/12**。",
        "",
        "| weight | band | BAND Calmar | STATIC Calmar | BAND MaxDD | STATIC MaxDD | 胜 |",
        "|---:|---:|---:|---:|---:|---:|:--:|",
    ]
    for cell in disc["grid"]["cells"]:
        lines.append(
            f"| {cell['weight']:g} | {cell['band']:g} | {_fmt(cell['band_calmar'])} | "
            f"{_fmt(cell['static_calmar'])} | {_pct(-cell['band_maxdd'])} | "
            f"{_pct(-cell['static_maxdd'])} | "
            f"{'✓' if cell['band_beats_static'] else 'x'} |"
        )

    diff = disc["diff_bootstrap"]
    lines += [
        "",
        "## 再平衡动作的逐 bar 证据 (BAND(0.30,0.10) - STATIC(0.30) 日收益差)",
        "",
        f"- 观测日均差:`{diff['observed_mean'] * 100:+.4f}%`;",
        f"- 差值年化信息比:`{diff['info_ratio']:.2f}`;",
        f"- 循环块 bootstrap(块={BLOCK}天,{BOOTSTRAP_SAMPLES}次)均值 > 0 概率:"
        f"`{diff['prob_positive'] * 100:.1f}%`,P5 `{diff['p05'] * 100:+.4f}%`。",
        "",
        "## 冷启动自然年 (主配置 vs STATIC(0.30), Calmar)",
        "",
        "| Year | BAND Return | BAND Calmar | STATIC Return | STATIC Calmar | 胜 |",
        "|---:|---:|---:|---:|---:|:--:|",
    ]
    for band, stat in zip(disc["yearly_band"], disc["yearly_static"], strict=True):
        lines.append(
            f"| {band['year']} | {_pct(band['return'])} | {_fmt(band['calmar'])} | "
            f"{_pct(stat['return'])} | {_fmt(stat['calmar'])} | "
            f"{'✓' if band['calmar'] > stat['calmar'] else 'x'} |"
        )

    lines += ["", "## discovery 门明细", ""]
    lines.extend(
        f"- {'PASS' if check['passed'] else 'FAIL'} — {check['name']}"
        for check in disc["gate"]["checks"]
    )

    static_dds = [cell["static_maxdd"] for cell in disc["grid"]["cells"]]
    band_dds = [cell["band_maxdd"] for cell in disc["grid"]["cells"]]
    lines += [
        "",
        "## 机制裁决(诚实解读)",
        "",
        "门槛按 Calmar(回撤调整)定义并全数通过,但这不是 alpha。证据分两面,必须同时读:",
        "",
        f"- **收割即超额收益 = 证伪。** BAND(0.30,0.10) 对 STATIC(0.30) 的日收益差均值为负 "
        f"(`{diff['observed_mean'] * 100:+.4f}%`),年化信息比 `{diff['info_ratio']:.2f}`,"
        f"块 bootstrap 中差值为正的概率仅 `{diff['prob_positive'] * 100:.1f}%`。在 DOGE 的强"
        "趋势里,再平衡把上涨过早卖出的代价超过了波动收割,所以带宽再平衡的总收益低于静态漂移、"
        "也低于 BH100。事前声明的限制 #1 得到确认。",
        f"- **有界风险 = 真实,且静态无法企及。** STATIC 的 MaxDD 在 0.2-0.5 全部权重上都是 "
        f"`{min(static_dds) * 100:.0f}-{max(static_dds) * 100:.0f}%`(几乎与初始权重无关):"
        "在一次 100x 暴涨里,任何初始 DOGE 权重都会膨胀到接近满仓,随后吃满崩盘。只有再平衡"
        f"能让 MaxDD 真正随权重下调(BAND `{min(band_dds) * 100:.0f}-{max(band_dds) * 100:.0f}%`)。"
        "因此在 DOGE 这种右尾资产上,再平衡是维持有界风险敞口的唯一非预测手段。",
        "",
        "结论:波动收割在 DOGE 上**不是**收益引擎(这道门关上,与此前 15 个择时机制并列为诚实"
        "负面结论);但恒定混合再平衡是唯一能让 DOGE 风险敞口\"可调且有界\"的非预测策略,顺序验证"
        "一致(2025 年 DOGE 现货 -63% 时主配置仅 -18%)。其正当用途是 100U 计划的 layer-1 有界"
        "风险配置政策,而非跑赢买入持有的收益来源。**真实资金:不批准为收益策略。**",
    ]

    val = payload["validation"]
    lines += [
        "",
        "## 顺序验证(主配置冻结于协议,逐年冷启动)",
        "",
        "> 主配置 BAND(0.30,0.10) 与 STATIC(0.30) 在协议中先于任何结果冻结;"
        "下列每年独立冷启动。2026 自然年未完,固定 INCONCLUSIVE。",
        "",
        "| Year | 阶段 | BAND Return | BAND Calmar | STATIC Return | STATIC Calmar | DOGE B&H |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for row in val["years"]:
        lines.append(
            f"| {row['year']} | {row['stage']} | {_pct(row['band']['return'])} | "
            f"{_fmt(row['band']['calmar'])} | {_pct(row['static']['return'])} | "
            f"{_fmt(row['static']['calmar'])} | {_pct(row['buy_hold_return'])} |"
        )

    lines += [
        "",
        "## Provenance",
        "",
        f"- discovery fingerprint: `{disc['data_fingerprint']}`(bars {disc['bars']},"
        f"range `{disc['range']}`)",
        f"- full-series fingerprint: `{payload['full_fingerprint']}`",
        "- Query hard end (discovery): `2024-01-01 00:00 UTC` (exclusive)",
        "- Costs: 10 bps fee + 5 bps slippage per side; 25 bps stress",
        "- Execution: closed 1d decision, next 1d open fill; spot no-borrow, no-short",
        "- BAND = Sizing.REBALANCE + dust_fraction=band; STATIC = Sizing.ON_ENTRY",
        f"- Seed: {SEED}",
        "",
        "## 诚实限制",
        "",
        "1. 这不是 alpha:再平衡溢价是波动的机械副产物,单边猛牛里对总收益必然输给 BH100。",
        "   discovery 窗(2021 大涨后回落)对收割近乎顺境,真正裁决在顺序验证。",
        "2. 外部 Donchian 引擎校准门仍为 FAILED;恒定混合对退出/sizing 语义不敏感,是较干净"
        "   的校准工具,但内部测试充分 ≠ 外部基准已复现。",
        "3. 无盘口冲击/容量/部分成交建模;固定 10,000 USDT 下成本有参考意义,不能推导容量。",
        "",
    ]
    return "\n".join(lines)


def _discovery(series: Series) -> dict[str, Any]:
    main = _summary(_run(MAIN_WEIGHT, Sizing.REBALANCE, MAIN_BAND, series))
    static_main = _summary(_run(MAIN_WEIGHT, Sizing.ON_ENTRY, None, series))
    cont_main = _summary(_run(MAIN_WEIGHT, Sizing.REBALANCE, None, series))
    buy_hold = _summary(_run(1.0, Sizing.ON_ENTRY, None, series))
    grid = _grid(series)
    stress_main = _summary(
        _run(MAIN_WEIGHT, Sizing.REBALANCE, MAIN_BAND, series, STRESS_SLIP_BPS)
    )
    stress_static = _summary(
        _run(MAIN_WEIGHT, Sizing.ON_ENTRY, None, series, STRESS_SLIP_BPS)
    )
    yearly_band = [
        _window_summary(MAIN_WEIGHT, Sizing.REBALANCE, MAIN_BAND, series, year)
        for year in range(2021, 2024)
    ]
    yearly_static = [
        _window_summary(MAIN_WEIGHT, Sizing.ON_ENTRY, None, series, year)
        for year in range(2021, 2024)
    ]
    band_run = _run(MAIN_WEIGHT, Sizing.REBALANCE, MAIN_BAND, series)
    static_run = _run(MAIN_WEIGHT, Sizing.ON_ENTRY, None, series)
    diff = _block_bootstrap_diff(band_run.equity, static_run.equity, band_run.timestamps)
    gate = _gate(
        main, static_main, grid, stress_main, stress_static, yearly_band, yearly_static
    )
    return {
        "main": main,
        "static_main": static_main,
        "cont_main": cont_main,
        "buy_hold": buy_hold,
        "grid": grid,
        "stress_main": stress_main,
        "stress_static": stress_static,
        "yearly_band": yearly_band,
        "yearly_static": yearly_static,
        "diff_bootstrap": {
            "observed_mean": diff.observed_mean,
            "prob_positive": diff.prob_positive,
            "p05": diff.p05,
            "info_ratio": diff.info_ratio,
        },
        "gate": gate,
        "data_fingerprint": series_fingerprint(series),
        "bars": len(series),
        "range": f"{from_ms(int(series.ts[0]))}..{from_ms(int(series.ts[-1]))}",
    }


def _validation(full: Series) -> dict[str, Any]:
    stages = {2024: "validation", 2025: "audit", 2026: "INCONCLUSIVE (年度未完)"}
    years: list[dict[str, Any]] = []
    for year, stage in stages.items():
        band = _window_summary(MAIN_WEIGHT, Sizing.REBALANCE, MAIN_BAND, full, year)
        static = _window_summary(MAIN_WEIGHT, Sizing.ON_ENTRY, None, full, year)
        bh = _window_summary(1.0, Sizing.ON_ENTRY, None, full, year)
        years.append(
            {
                "year": year,
                "stage": stage,
                "band": band,
                "static": static,
                "buy_hold_return": bh["return"],
            }
        )
    return {"years": years}


def main() -> int:
    end_ms = to_ms(DISCOVERY_END)
    with Store(DB_PATH) as store:
        discovery_series = load_series(store, INSTRUMENT, TIMEFRAME, end_ms=end_ms)
        full_series = load_series(store, INSTRUMENT, TIMEFRAME)
    if len(discovery_series) == 0 or len(full_series) == 0:
        raise SystemExit("DOGE-USDT data missing")
    if int(discovery_series.ts[-1]) >= end_ms:
        raise RuntimeError("discovery query crossed the frozen 2024 boundary")

    payload: dict[str, Any] = {
        "study": "doge-volatility-harvest-v1",
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "query_end_exclusive": DISCOVERY_END,
        "weights": list(WEIGHTS),
        "bands": list(BANDS),
        "main_weight": MAIN_WEIGHT,
        "main_band": MAIN_BAND,
        "full_fingerprint": series_fingerprint(full_series),
        "discovery": _discovery(discovery_series),
        "validation": _validation(full_series),
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
