#!/usr/bin/env python
"""Pre-2024 discovery for the single-asset 1h tail-conditioned reversal (TCR v1).

Direction A of the 1h DOGE-spot study, and the main candidate. Frozen in
``TAIL_REVERSAL_1H_PROTOCOL_2026-07-23.md`` before this ran. Buy DOGE spot only
after its own N-hour drop enters the causal q-tail of its recent N-hour return
distribution and the last hour has turned up; hold M hours; cool down 48h so
episodes stay sparse enough to survive 15bps/side cost. Single asset only — no
BTC/ETH/swap/funding. Every query has an exclusive 2024 boundary.
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
    position_spans,
    trades_from_fills,
)
from cq.research.split import from_ms, to_ms
from cq.research.stats import bootstrap_trades, sidak_correction

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
FAMILY_TRIALS = 5
OUTPUT_JSON = Path("reports/research/doge_tail_reversal_1h_discovery.json")
OUTPUT_MD = Path(
    "docs/research/doge-spot/TAIL_REVERSAL_1H_DISCOVERY_RESULTS_2026-07-23.md"
)


class ResearchStrategy(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def warmup_bars(self) -> int: ...

    def reset(self) -> None: ...

    def on_bar(self, ctx: Context) -> Intent: ...


@dataclass(frozen=True)
class TcrParams:
    """Frozen tail-conditioned reversal parameters."""

    shock_hours: int = 6
    calibration_hours: int = 2_160
    tail_quantile: float = 0.05
    hold_hours: int = 12
    cooldown_after_exit: int = 48
    size: float = 0.25
    require_confirmation: bool = True
    require_tail: bool = True

    def __post_init__(self) -> None:
        if self.shock_hours < 1:
            raise ValueError("shock_hours must be positive")
        if self.calibration_hours < self.shock_hours:
            raise ValueError("calibration_hours cannot be shorter than shock_hours")
        if not 0 < self.tail_quantile < 1:
            raise ValueError("tail_quantile must be in (0, 1)")
        if self.hold_hours < 1:
            raise ValueError("hold_hours must be positive")
        if self.cooldown_after_exit < 0:
            raise ValueError("cooldown_after_exit cannot be negative")
        if not 0 < self.size <= 1:
            raise ValueError("spot size must be in (0, 1]")


class DogeTailReversal:
    """Buy DOGE after its own N-hour drop enters the causal tail; hold M hours."""

    def __init__(self, params: TcrParams | None = None):
        self.params = params or TcrParams()
        self._target = 0.0
        self._signal_index: int | None = None
        self._blocked_until = -1

    @property
    def name(self) -> str:
        p = self.params
        confirm = "confirmed" if p.require_confirmation else "raw"
        tail = f"q{p.tail_quantile * 100:g}" if p.require_tail else "notail"
        return f"doge-tcr-n{p.shock_hours}-{tail}-h{p.hold_hours}-{confirm}"

    @property
    def warmup_bars(self) -> int:
        return self.params.calibration_hours + self.params.shock_hours + 1

    def reset(self) -> None:
        self._target = 0.0
        self._signal_index = None
        self._blocked_until = -1

    def snapshot_state(self) -> dict[str, object]:
        return {
            "target": self._target,
            "signal_index": self._signal_index,
            "blocked_until": self._blocked_until,
            "params": asdict(self.params),
        }

    def restore_state(self, state: dict[str, object]) -> None:
        if state.get("params") != asdict(self.params):
            raise ValueError("TCR checkpoint configuration does not match")
        raw_target = state.get("target")
        raw_signal = state.get("signal_index")
        raw_blocked = state.get("blocked_until")
        if (
            isinstance(raw_target, bool)
            or not isinstance(raw_target, (int, float))
            or float(raw_target) not in (0.0, self.params.size)
        ):
            raise ValueError("invalid TCR checkpoint target")
        if raw_signal is not None and (
            isinstance(raw_signal, bool) or not isinstance(raw_signal, int)
        ):
            raise ValueError("invalid TCR checkpoint signal index")
        if isinstance(raw_blocked, bool) or not isinstance(raw_blocked, int):
            raise ValueError("invalid TCR checkpoint cooldown")
        if (float(raw_target) > 0) != (raw_signal is not None):
            raise ValueError("TCR position and signal index disagree")
        self._target = float(raw_target)
        self._signal_index = raw_signal
        self._blocked_until = raw_blocked

    def on_bar(self, ctx: Context) -> Intent:
        p = self.params
        if self._target > 0.0:
            if self._signal_index is None:
                raise RuntimeError("TCR position has no signal index")
            if ctx.index - self._signal_index >= p.hold_hours:
                self._target = 0.0
                self._signal_index = None
            return Intent(target=self._target, reason=self.name)

        if ctx.index < self._blocked_until:
            return Intent(target=0.0, reason=self.name)

        n = self.warmup_bars
        returns = np.diff(np.log(ctx.close(n)))
        h = p.shock_hours
        shock = float(np.sum(returns[-h:]))
        calibration = returns[:-h]
        if len(calibration) < h:
            return Intent(target=0.0, reason=f"{self.name}-short-calibration")
        past_blocks = np.convolve(calibration, np.ones(h, dtype=float), mode="valid")
        tail_cut = float(np.quantile(past_blocks, p.tail_quantile, method="linear"))

        tail_ok = not p.require_tail or shock < tail_cut
        confirmation = not p.require_confirmation or returns[-1] > 0.0
        if tail_ok and shock < 0.0 and confirmation:
            self._target = p.size
            self._signal_index = ctx.index
            self._blocked_until = ctx.index + p.hold_hours + p.cooldown_after_exit
        return Intent(target=self._target, reason=self.name)


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
            return Intent(target=0.0, reason=f"{self.name}-before")
        if ctx.decision_time >= self.end_ms:
            return Intent(target=0.0, reason=f"{self.name}-after")
        return self.inner.on_bar(ctx)


def candidate_factories() -> dict[str, Callable[[], DogeTailReversal]]:
    return {
        "main": DogeTailReversal,
        "q025": lambda: DogeTailReversal(TcrParams(tail_quantile=0.025)),
        "q10": lambda: DogeTailReversal(TcrParams(tail_quantile=0.10)),
        "hold6": lambda: DogeTailReversal(TcrParams(hold_hours=6)),
        "hold24": lambda: DogeTailReversal(TcrParams(hold_hours=24)),
        "no_confirm": lambda: DogeTailReversal(TcrParams(require_confirmation=False)),
        "plain_dip": lambda: DogeTailReversal(
            TcrParams(require_tail=False, require_confirmation=False)
        ),
    }


def _run(
    strategy: ResearchStrategy, series: Series, slippage_bps: float = BASE_SLIPPAGE_BPS
) -> RunResult:
    return run_backtest(
        strategy,
        series,
        MarketSpec(INSTRUMENT, "spot"),
        INITIAL_CASH,
        costs=CostModel(fee_bps=BASE_FEE_BPS, slippage_bps=slippage_bps),
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
    return {
        "return": metrics.total_return,
        "cagr": metrics.cagr,
        "sharpe": metrics.sharpe,
        "max_drawdown": metrics.max_drawdown,
        "longest_drawdown_days": metrics.longest_drawdown_days,
        "trades": metrics.trades,
        "win_rate": metrics.win_rate,
        "profit_factor": metrics.profit_factor,
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


def _matched_random_null(
    series: Series,
    spans: list[tuple[int, int | None]],
    observed: float,
    size: float = TcrParams().size,
    samples: int = SAMPLES,
    seed: int = SEED,
) -> dict[str, float | int]:
    """Random entries matched by entry year, holding bars, size and costs."""
    if not spans:
        return {
            "samples": samples, "trades_matched": 0, "family_trials": FAMILY_TRIALS,
            "observed": observed, "null_p05": 0.0, "null_median": 0.0,
            "null_p95": 0.0, "p_value": 1.0, "family_adjusted_p": 1.0,
        }
    index_of = {int(ts): i for i, ts in enumerate(series.ts)}
    years = np.array([int(from_ms(int(ts))[:4]) for ts in series.ts], dtype=int)
    indexes = np.arange(len(series), dtype=int)
    rng = np.random.default_rng(seed)
    totals = np.ones(samples, dtype=float)
    fee = BASE_FEE_BPS / 10_000
    slip = BASE_SLIPPAGE_BPS / 10_000
    gross_entry = (1.0 + slip) * (1.0 + fee)

    for entry_ts, exit_ts in spans:
        if exit_ts is None:
            raise ValueError("TCR discovery null requires closed episodes")
        entry_index = index_of[int(entry_ts)]
        exit_index = index_of[int(exit_ts)]
        holding_bars = exit_index - entry_index
        if holding_bars < 1:
            raise ValueError("TCR episodes must hold at least one bar")
        valid_end = indexes + holding_bars < len(series)
        valid_volume = np.zeros(len(series), dtype=bool)
        candidates_with_end = indexes[valid_end]
        valid_volume[candidates_with_end] = (
            series.volume[candidates_with_end] > 0
        ) & (series.volume[candidates_with_end + holding_bars] > 0)
        candidates = indexes[(years == years[entry_index]) & valid_end & valid_volume]
        if len(candidates) == 0:
            raise ValueError("no year-matched random entry candidates")
        starts = rng.choice(candidates, size=samples, replace=True)
        exits = starts + holding_bars
        gross_exit = (
            series.open[exits] / series.open[starts] * (1.0 - slip) * (1.0 - fee)
        )
        totals *= 1.0 + size * (gross_exit - gross_entry)

    null_returns = totals - 1.0
    exceedances = int(np.sum(null_returns >= observed))
    p_value = (exceedances + 1) / (samples + 1)
    return {
        "samples": samples, "trades_matched": len(spans), "family_trials": FAMILY_TRIALS,
        "observed": observed, "null_p05": float(np.percentile(null_returns, 5)),
        "null_median": float(np.median(null_returns)),
        "null_p95": float(np.percentile(null_returns, 95)),
        "p_value": p_value, "family_adjusted_p": sidak_correction(p_value, FAMILY_TRIALS),
    }


def _gate(
    main: dict[str, Any], stress: dict[str, Any], yearly: list[dict[str, Any]],
    neighbors: dict[str, dict[str, Any]], no_confirm: dict[str, Any],
    plain: dict[str, Any], random_null: dict[str, float | int],
) -> dict[str, Any]:
    checks = [
        ("15 bps return > 0", main["return"] > 0),
        ("15 bps Sharpe >= 0.50", main["sharpe"] >= 0.50),
        ("MaxDD <= 20%", main["max_drawdown"] <= 0.20),
        ("at least 20 closed trades", main["trades"] >= 20),
        (
            "at least two positive cold-start years",
            sum(row["return"] > 0 for row in yearly) >= 2,
        ),
        ("25 bps/side return > 0", stress["return"] > 0),
        ("return less best closed trade > 0", main["return_less_best_1"] > 0),
        ("episode bootstrap P5 > 0", main["bootstrap_p05"] > 0),
        (
            "all four fixed neighbors profitable",
            all(row["return"] > 0 for row in neighbors.values()),
        ),
        (
            "main beats plain_dip on Sharpe and mean episode",
            main["sharpe"] > plain["sharpe"]
            and main["mean_episode_return"] > plain["mean_episode_return"],
        ),
        (
            "main mean episode beats no_confirm ablation",
            main["mean_episode_return"] > no_confirm["mean_episode_return"],
        ),
        (
            "year/holding matched random Sidak-adjusted p <= 0.10",
            float(random_null["family_adjusted_p"]) <= 0.10,
        ),
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
    null = payload["matched_random_null"]
    lines = [
        "# DOGE 单资产尾部条件反转发现结果 (TCR v1, 2021-2023)",
        "",
        "> 数据库层排他硬截止 2024-01-01; 未读取后续年度。单资产, 不用 BTC/ETH。",
        "> 承接方向 C: 只在自身急跌尾部稀疏做多, 试图收割反转毛 edge 的一小片而不被成本吞没。",
        "",
        "## 结论",
        "",
        f"**{payload['gate']['verdict']}**",
        "",
        "## 冻结主版本 (N=6, q=0.05, M=12, 15bps)",
        "",
        "| Return | Sharpe | MaxDD | Trades | Mean episode | Less best 1 | 25bps | Bootstrap P5 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"| {_pct(main['return'])} | {main['sharpe']:.2f} | "
        f"{_pct(-main['max_drawdown'])} | {main['trades']} | "
        f"{_pct(main['mean_episode_return'])} | {_pct(main['return_less_best_1'])} | "
        f"{_pct(stress['return'])} | {_pct(main['bootstrap_p05'])} |",
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
        "## 固定邻域与机制消融 (15bps)",
        "",
        "| Version | Return | Sharpe | MaxDD | Trades | Mean episode |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name in ("q025", "q10", "hold6", "hold24", "no_confirm", "plain_dip"):
        row = payload["variants"][name]
        lines.append(
            f"| {name} | {_pct(row['return'])} | {row['sharpe']:.2f} | "
            f"{_pct(-row['max_drawdown'])} | {row['trades']} | "
            f"{_pct(row['mean_episode_return'])} |"
        )
    lines += [
        "",
        "## 匹配随机入场",
        "",
        f"- Observed episode return: `{_pct(float(null['observed']))}`",
        f"- Random median: `{_pct(float(null['null_median']))}`",
        f"- Random P5-P95: `{_pct(float(null['null_p05']))}` .. `{_pct(float(null['null_p95']))}`",
        f"- Raw one-sided p: `{float(null['p_value']):.6f}`",
        f"- Sidak-adjusted p ({null['family_trials']} versions): "
        f"`{float(null['family_adjusted_p']):.6f}`",
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
        "- Execution: closed 1h decision, next open fill, 25% spot target",
        "- Protocol: `TAIL_REVERSAL_1H_PROTOCOL_2026-07-23.md`",
        "",
    ]
    if not payload["gate"]["passed"]:
        lines += [
            "按冻结规则, TCR v1 在 discovery 永久停止; 不读取 2024, 不从邻域替补, 不调参。",
            "",
        ]
    return "\n".join(lines)


def main() -> int:
    end_ms = to_ms(DISCOVERY_END)
    with Store(DB_PATH) as store:
        series = load_series(store, INSTRUMENT, TIMEFRAME, end_ms=end_ms)
    if len(series) == 0:
        raise SystemExit("TCR discovery market data missing")
    if int(series.ts[-1]) >= end_ms:
        raise RuntimeError("TCR discovery query crossed the frozen 2024 boundary")

    factories = candidate_factories()
    results = {name: _run(factory(), series) for name, factory in factories.items()}
    summaries = {name: _summary(result) for name, result in results.items()}
    main_result = results["main"]
    main_summary = summaries["main"]
    stress = _summary(_run(factories["main"](), series, slippage_bps=STRESS_SLIPPAGE_BPS))
    yearly = [_cold_year(series, factories["main"], year) for year in range(2021, 2024)]
    spans = position_spans(main_result.fills)
    episodes = episode_returns(
        main_result.timestamps, main_result.equity, main_result.fills,
        main_result.initial_cash,
    )
    observed = float(np.prod(1.0 + np.asarray(episodes, dtype=float)) - 1.0)
    random_null = _matched_random_null(series, spans, observed)
    neighbors = {name: summaries[name] for name in ("q025", "q10", "hold6", "hold24")}
    gate = _gate(
        main_summary, stress, yearly, neighbors,
        summaries["no_confirm"], summaries["plain_dip"], random_null,
    )
    payload: dict[str, Any] = {
        "study": "doge-tail-reversal-1h-v1",
        "stage": "discovery",
        "direction": "A",
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "query_end_exclusive": DISCOVERY_END,
        "params": asdict(TcrParams()),
        "family_trials": FAMILY_TRIALS,
        "fingerprint": series_fingerprint(series),
        "bars": len(series),
        "range": f"{from_ms(int(series.ts[0]))}..{from_ms(int(series.ts[-1]))}",
        "main": main_summary,
        "stress_25bps": stress,
        "yearly": yearly,
        "variants": {name: row for name, row in summaries.items() if name != "main"},
        "matched_random_null": random_null,
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
