#!/usr/bin/env python
"""DOGE-only Volatility Compression-Spot Expansion research.

The frozen specification is documented in
``docs/research/doge-spot/VCSE_PREREGISTRATION_2026-07-22.md``. This module
implements that specification against the project's causal Context and unified
backtest loop. It never reads BTC, ETH, swaps, funding, OI, or future bars.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, cast

import numpy as np

from cq.context import Context, Series, series_fingerprint
from cq.core.types import CostModel, Intent, MarketSpec, Sizing
from cq.data.feed import load_series
from cq.data.store import Store
from cq.engine.loop import RunResult, run_backtest
from cq.research.metrics import (
    bars_per_year,
    compute_metrics,
    episode_returns,
    max_drawdown,
    per_bar_returns,
    sharpe_ratio,
    trades_from_fills,
)
from cq.research.split import from_ms
from cq.research.stats import bootstrap_trades

DB_PATH = "data/cq.db"
INSTRUMENT = "DOGE-USDT"
TIMEFRAME = "4h"
INITIAL_CASH = 10_000.0
BASE_FEE_BPS = 10.0
BASE_SLIPPAGE_BPS = 5.0
OUTPUT_JSON = Path("reports/research/doge_vcse_results.json")
OUTPUT_MD = Path("docs/research/doge-spot/VCSE_RESULTS_2026-07-22.md")


@dataclass(frozen=True)
class VcseParams:
    atr_bars: int = 18
    compression_history: int = 540
    compression_quantile: float = 0.20
    compression_recency: int = 3
    breakout_bars: int = 30
    expansion_multiplier: float = 1.25
    clv_min: float = 0.70
    volume_bars: int = 30
    volume_multiplier: float = 1.50
    exit_bars: int = 10
    trailing_atr: float = 3.0
    max_hold_bars: int = 60
    size: float = 1.0
    use_compression: bool = True
    use_expansion: bool = True
    use_clv: bool = True
    use_volume: bool = True

    def __post_init__(self) -> None:
        integer_fields = (
            self.atr_bars,
            self.compression_history,
            self.compression_recency,
            self.breakout_bars,
            self.volume_bars,
            self.exit_bars,
            self.max_hold_bars,
        )
        if any(value < 2 for value in integer_fields):
            raise ValueError("all lookbacks must be at least two bars")
        if not 0 < self.compression_quantile < 1:
            raise ValueError("compression_quantile must be between zero and one")
        if not 0 <= self.clv_min <= 1:
            raise ValueError("clv_min must be between zero and one")
        if min(
            self.expansion_multiplier,
            self.volume_multiplier,
            self.trailing_atr,
            self.size,
        ) <= 0:
            raise ValueError("multipliers and size must be positive")


class DogeVcse:
    """Long-only DOGE spot expansion following a causal volatility compression."""

    def __init__(self, params: VcseParams | None = None):
        self.params = params or VcseParams()
        self._target = 0.0
        self._entry_index: int | None = None
        self._peak_close = 0.0

    @property
    def name(self) -> str:
        p = self.params
        disabled = "".join(
            name
            for flag, name in (
                (not p.use_compression, "-no-comp"),
                (not p.use_expansion, "-no-exp"),
                (not p.use_clv, "-no-clv"),
                (not p.use_volume, "-no-vol"),
            )
            if flag
        )
        return (
            f"doge-vcse-q{p.compression_quantile:g}-b{p.breakout_bars}"
            f"-x{p.expansion_multiplier:g}-v{p.volume_multiplier:g}{disabled}"
        )

    @property
    def warmup_bars(self) -> int:
        p = self.params
        compression = p.compression_history + p.atr_bars + p.compression_recency + 2
        return max(compression, p.breakout_bars + 2, p.volume_bars + 2)

    def reset(self) -> None:
        self._target = 0.0
        self._entry_index = None
        self._peak_close = 0.0

    def snapshot_state(self) -> dict[str, object]:
        return {
            "target": self._target,
            "entry_index": self._entry_index,
            "peak_close": self._peak_close,
            "params": asdict(self.params),
        }

    def on_bar(self, ctx: Context) -> Intent:
        p = self.params
        window = self.warmup_bars
        high = ctx.high(window)
        low = ctx.low(window)
        close = ctx.close(window)
        volume = ctx.volume(window)
        atr, atr_pct, true_range = _atr_state(high, low, close, p.atr_bars)
        current_close = float(close[-1])

        if self._target == 0.0:
            if self._entry_signal(high, low, close, volume, atr, atr_pct, true_range):
                self._target = p.size
                self._entry_index = ctx.index
                self._peak_close = current_close
        else:
            self._peak_close = max(self._peak_close, current_close)
            prior_exit_low = float(np.min(low[-p.exit_bars - 1 : -1]))
            trail = self._peak_close - p.trailing_atr * float(atr[-1])
            held = ctx.index - (self._entry_index if self._entry_index is not None else ctx.index)
            if current_close < prior_exit_low or current_close < trail or held >= p.max_hold_bars:
                self._target = 0.0
                self._entry_index = None
                self._peak_close = 0.0

        return Intent(target=self._target, reason=self.name)

    def _entry_signal(
        self,
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        volume: np.ndarray,
        atr: np.ndarray,
        atr_pct: np.ndarray,
        true_range: np.ndarray,
    ) -> bool:
        p = self.params
        compression = True
        if p.use_compression:
            compression = False
            current = len(close) - 1
            for offset in range(1, p.compression_recency + 1):
                candidate = current - offset
                history = atr_pct[candidate - p.compression_history : candidate]
                value = atr_pct[candidate]
                if len(history) != p.compression_history or not np.all(np.isfinite(history)):
                    continue
                if math.isfinite(float(value)) and value < np.quantile(
                    history, p.compression_quantile
                ):
                    compression = True
                    break

        breakout = float(close[-1]) > float(np.max(high[-p.breakout_bars - 1 : -1]))
        expansion = (not p.use_expansion) or (
            float(true_range[-1]) > p.expansion_multiplier * float(atr[-2])
        )
        spread = float(high[-1] - low[-1])
        clv = (float(close[-1] - low[-1]) / spread) if spread > 0 else 0.0
        strong_close = (not p.use_clv) or clv >= p.clv_min
        median_volume = float(np.median(volume[-p.volume_bars - 1 : -1]))
        volume_ok = (not p.use_volume) or (
            median_volume > 0 and float(volume[-1]) >= p.volume_multiplier * median_volume
        )
        return compression and breakout and expansion and strong_close and volume_ok


def _atr_state(
    high: np.ndarray, low: np.ndarray, close: np.ndarray, bars: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Causal simple ATR aligned to input bars; no current value enters its past."""
    true_range = np.full(len(close), np.nan, dtype=float)
    true_range[1:] = np.maximum.reduce(
        (
            high[1:] - low[1:],
            np.abs(high[1:] - close[:-1]),
            np.abs(low[1:] - close[:-1]),
        )
    )
    atr = np.full(len(close), np.nan, dtype=float)
    finite_tr = np.nan_to_num(true_range, nan=0.0)
    cumulative = np.cumsum(finite_tr)
    for index in range(bars, len(close)):
        left = index - bars + 1
        total = cumulative[index] - (cumulative[left - 1] if left > 0 else 0.0)
        atr[index] = total / bars
    with np.errstate(divide="ignore", invalid="ignore"):
        atr_pct = atr / close
    return atr, atr_pct, true_range


class BuyAndHold:
    name = "buy-and-hold"
    warmup_bars = 2

    def __init__(self, size: float = 1.0):
        self.size = size

    def reset(self) -> None:
        pass

    def on_bar(self, ctx: Context) -> Intent:
        return Intent(target=self.size, reason=self.name)


def _run(
    series: Series,
    params: VcseParams,
    fee_bps: float = BASE_FEE_BPS,
    slippage_bps: float = BASE_SLIPPAGE_BPS,
) -> RunResult:
    return run_backtest(
        DogeVcse(params),
        series,
        MarketSpec(INSTRUMENT, "spot"),
        INITIAL_CASH,
        costs=CostModel(fee_bps=fee_bps, slippage_bps=slippage_bps),
        sizing=Sizing.ON_ENTRY,
    )


def _summary(result: RunResult) -> dict[str, Any]:
    metrics = compute_metrics(
        result.timestamps, result.equity, result.fills, result.initial_cash
    )
    episodes = episode_returns(
        result.timestamps, result.equity, result.fills, result.initial_cash
    )
    bootstrap = bootstrap_trades(episodes, samples=10_000, seed=20260722)
    trades = trades_from_fills(result.fills)
    net = sorted((trade.net_pnl for trade in trades), reverse=True)
    final = result.final_equity

    def less_best(count: int) -> float:
        return (final - sum(net[:count])) / result.initial_cash - 1.0

    return {
        "return": metrics.total_return,
        "cagr": metrics.cagr,
        "sharpe": metrics.sharpe,
        "max_drawdown": metrics.max_drawdown,
        "longest_drawdown_days": metrics.longest_drawdown_days,
        "trades": metrics.trades,
        "win_rate": metrics.win_rate,
        "profit_factor": metrics.profit_factor,
        "return_less_best_1": less_best(1),
        "return_less_best_3": less_best(3),
        "return_less_best_5": less_best(5),
        "bootstrap_probability_of_loss": bootstrap.probability_of_loss,
        "bootstrap_p05": bootstrap.percentile_05,
        "bootstrap_median": bootstrap.median,
        "bootstrap_p95": bootstrap.percentile_95,
        "fills": len(result.fills),
        "rejections": len(result.rejections),
    }


def _annual(result: RunResult) -> list[dict[str, Any]]:
    stamps = np.asarray(result.timestamps, dtype=np.int64)
    equity = np.asarray(result.equity, dtype=float)
    years = np.array([int(from_ms(int(ts))[:4]) for ts in stamps])
    trades = trades_from_fills(result.fills)
    out: list[dict[str, Any]] = []
    for year in sorted(set(years)):
        indexes = np.flatnonzero(years == year)
        if len(indexes) < 2:
            continue
        values = equity[indexes]
        opening = equity[indexes[0] - 1] if indexes[0] > 0 else result.initial_cash
        returns = per_bar_returns(np.r_[opening, values])
        year_trades = [t for t in trades if int(from_ms(t.exit_ts)[:4]) == year]
        out.append(
            {
                "year": int(year),
                "return": float(values[-1] / opening - 1.0),
                "sharpe": sharpe_ratio(returns, bars_per_year(stamps[indexes])),
                "max_drawdown": max_drawdown(np.r_[opening, values]),
                "trades_closed": len(year_trades),
            }
        )
    return out


def _variant_definitions(main: VcseParams) -> dict[str, VcseParams]:
    return {
        "q15": replace(main, compression_quantile=0.15),
        "q25": replace(main, compression_quantile=0.25),
        "breakout24": replace(main, breakout_bars=24),
        "breakout36": replace(main, breakout_bars=36),
        "expansion100": replace(main, expansion_multiplier=1.00),
        "expansion150": replace(main, expansion_multiplier=1.50),
        "volume125": replace(main, volume_multiplier=1.25),
        "volume175": replace(main, volume_multiplier=1.75),
        "trail25": replace(main, trailing_atr=2.5),
        "trail35": replace(main, trailing_atr=3.5),
        "hold42": replace(main, max_hold_bars=42),
        "hold78": replace(main, max_hold_bars=78),
    }


def _ablation_definitions(main: VcseParams) -> dict[str, VcseParams]:
    return {
        "no_compression": replace(main, use_compression=False),
        "no_volume": replace(main, use_volume=False),
        "no_clv": replace(main, use_clv=False),
        "breakout_only": replace(
            main,
            use_compression=False,
            use_expansion=False,
            use_clv=False,
            use_volume=False,
        ),
    }


def _fmt_pct(value: float | int) -> str:
    return f"{float(value) * 100:+.2f}%"


def _render(payload: dict[str, Any]) -> str:
    main = cast(dict[str, Any], payload["main"])
    annual = cast(list[dict[str, Any]], payload["annual"])
    variants = cast(dict[str, dict[str, Any]], payload["variants"])
    ablations = cast(dict[str, dict[str, Any]], payload["ablations"])
    stress = cast(dict[str, dict[str, Any]], payload["cost_stress"])
    lines = [
        "# DOGE VCSE 历史探索结果 (2026-07-22)",
        "",
        "> 规则在结果未知时预注册。全部数据早于/等于 forward freeze, 以下不是 OOS。",
        "",
        "## 主策略",
        "",
        "| Return | CAGR | Sharpe | MaxDD | Trades | PF | Less best 1 |",
        "|---:|---:|---:|---:|---:|---:|---:|",
        (
            f"| {_fmt_pct(main['return'])} | {_fmt_pct(main['cagr'])} | "
            f"{main['sharpe']:.2f} | {_fmt_pct(-float(main['max_drawdown']))} | "
            f"{main['trades']} | {main['profit_factor']:.2f} | "
            f"{_fmt_pct(main['return_less_best_1'])} |"
        ),
        "",
        "## 自然年",
        "",
        "| Year | Return | Sharpe | MaxDD | Closed trades |",
        "|---:|---:|---:|---:|---:|",
    ]
    for row in annual:
        lines.append(
            f"| {row['year']} | {_fmt_pct(row['return'])} | {row['sharpe']:.2f} | "
            f"{_fmt_pct(-float(row['max_drawdown']))} | {row['trades_closed']} |"
        )
    lines += [
        "",
        "## 成本压力",
        "",
        "| Cost/side | Return | Sharpe | MaxDD | Trades |",
        "|---:|---:|---:|---:|---:|",
    ]
    for name, row in stress.items():
        lines.append(
            f"| {name} | {_fmt_pct(row['return'])} | {row['sharpe']:.2f} | "
            f"{_fmt_pct(-float(row['max_drawdown']))} | {row['trades']} |"
        )
    for title, rows in (("单因素邻域", variants), ("机制消融", ablations)):
        lines += [
            "",
            f"## {title}",
            "",
            "| Variant | Return | Sharpe | MaxDD | Trades |",
            "|---|---:|---:|---:|---:|",
        ]
        for name, row in rows.items():
            lines.append(
                f"| {name} | {_fmt_pct(row['return'])} | {row['sharpe']:.2f} | "
                f"{_fmt_pct(-float(row['max_drawdown']))} | {row['trades']} |"
            )
    gate = cast(dict[str, Any], payload["historical_gate"])
    lines += [
        "",
        "## 预注册门槛",
        "",
        f"**{'PASS' if gate['passed'] else 'FAIL'}**",
        "",
    ]
    lines.extend(
        f"- {'PASS' if item['passed'] else 'FAIL'} - {item['name']}"
        for item in gate["checks"]
    )
    lines += [
        "",
        "## Provenance",
        "",
        f"- Data fingerprint: `{payload['data_fingerprint']}`",
        f"- Bars: {payload['bars']}",
        f"- Range: {payload['range']}",
        "- Input: DOGE-USDT spot OHLCV only",
        "- Engine: unified causal loop, next-bar open execution, ON_ENTRY sizing",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    with Store(DB_PATH) as store:
        series = load_series(store, INSTRUMENT, TIMEFRAME)
    if len(series) == 0:
        raise SystemExit("DOGE-USDT data missing")

    params = VcseParams()
    main_result = _run(series, params)
    main_summary = _summary(main_result)
    variants = {
        name: _summary(_run(series, candidate))
        for name, candidate in _variant_definitions(params).items()
    }
    ablations = {
        name: _summary(_run(series, candidate))
        for name, candidate in _ablation_definitions(params).items()
    }
    stress = {
        "15 bps": main_summary,
        "25 bps": _summary(_run(series, params, fee_bps=10, slippage_bps=15)),
        "50 bps": _summary(_run(series, params, fee_bps=10, slippage_bps=40)),
    }

    buy_hold = run_backtest(
        BuyAndHold(),
        series,
        MarketSpec(INSTRUMENT, "spot"),
        INITIAL_CASH,
        costs=CostModel(fee_bps=BASE_FEE_BPS, slippage_bps=BASE_SLIPPAGE_BPS),
        sizing=Sizing.ON_ENTRY,
    )
    ablations["buy_and_hold"] = _summary(buy_hold)

    positive_years = sum(row["return"] > 0 for row in _annual(main_result) if row["year"] >= 2021)
    positive_neighbors = sum(row["return"] > 0 for row in variants.values())
    sharpe_neighbors = sum(row["sharpe"] > 0.30 for row in variants.values())
    breakout = ablations["breakout_only"]
    checks = [
        ("15 bps Sharpe >= 0.60", main_summary["sharpe"] >= 0.60),
        ("MaxDD <= 50%", main_summary["max_drawdown"] <= 0.50),
        ("at least 40 closed trades", main_summary["trades"] >= 40),
        ("at least 4 positive calendar years", positive_years >= 4),
        ("25 bps return remains positive", stress["25 bps"]["return"] > 0),
        ("return less best trade remains positive", main_summary["return_less_best_1"] > 0),
        ("at least 8/12 neighbors profitable", positive_neighbors >= 8),
        ("at least 6/12 neighbors Sharpe > 0.30", sharpe_neighbors >= 6),
        (
            "breakout-only does not clearly dominate full mechanism",
            not (
                breakout["return"] > main_summary["return"]
                and breakout["sharpe"] > main_summary["sharpe"] + 0.10
            ),
        ),
    ]
    gate = {
        "passed": all(passed for _, passed in checks),
        "checks": [{"name": name, "passed": bool(passed)} for name, passed in checks],
    }

    payload: dict[str, Any] = {
        "strategy": "DogeVcse",
        "params": asdict(params),
        "data_fingerprint": series_fingerprint(series),
        "bars": len(series),
        "range": f"{from_ms(int(series.ts[0]))}..{from_ms(int(series.ts[-1]))}",
        "main": main_summary,
        "annual": _annual(main_result),
        "cost_stress": stress,
        "variants": variants,
        "ablations": ablations,
        "historical_gate": gate,
    }
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    OUTPUT_MD.write_text(_render(payload), encoding="utf-8")
    print(_render(payload))
    print(f"JSON: {OUTPUT_JSON}")
    print(f"REPORT: {OUTPUT_MD}")
    return 0 if gate["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
