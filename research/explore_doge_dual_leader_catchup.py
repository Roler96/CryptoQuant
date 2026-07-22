#!/usr/bin/env python
"""Pre-2024 discovery for the frozen DOGE dual-leader catch-up hypothesis.

The result-blind formula, candidate family and gate are fixed in
``DUAL_LEADER_CATCHUP_PROTOCOL_2026-07-22.md``.  This process queries every
market with an exclusive 2024-01-01 boundary and must never expose a later bar.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

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
BTC_INSTRUMENT = "BTC-USDT"
ETH_INSTRUMENT = "ETH-USDT"
TIMEFRAME = "1h"
DISCOVERY_END = "2024-01-01"
INITIAL_CASH = 10_000.0
BASE_FEE_BPS = 10.0
BASE_SLIPPAGE_BPS = 5.0
STRESS_SLIPPAGE_BPS = 15.0
SAMPLES = 10_000
SEED = 20260722
FAMILY_TRIALS = 5
OUTPUT_JSON = Path("reports/research/doge_dual_leader_catchup_discovery.json")
OUTPUT_MD = Path(
    "docs/research/doge-spot/DUAL_LEADER_CATCHUP_DISCOVERY_RESULTS_2026-07-22.md"
)

ResidualMode = Literal["lagging", "already_led", "none"]


class ResearchStrategy(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def warmup_bars(self) -> int: ...

    def reset(self) -> None: ...

    def on_bar(self, ctx: Context) -> Intent: ...


@dataclass(frozen=True)
class DlcParams:
    """Frozen dual-leader catch-up parameters."""

    shock_hours: int = 6
    beta_history: int = 720
    leader_history: int = 2_160
    leader_quantile: float = 0.90
    hold_hours: int = 12
    cooldown_hours: int = 48
    size: float = 0.25
    residual_mode: ResidualMode = "lagging"
    require_doge_confirmation: bool = True

    def __post_init__(self) -> None:
        if self.shock_hours < 1:
            raise ValueError("shock_hours must be positive")
        if self.beta_history < 2:
            raise ValueError("beta_history must be at least two bars")
        if self.leader_history < 2:
            raise ValueError("leader_history must be at least two bars")
        if not 0 < self.leader_quantile < 1:
            raise ValueError("leader_quantile must be in (0, 1)")
        if self.hold_hours < 1:
            raise ValueError("hold_hours must be positive")
        if self.cooldown_hours < self.hold_hours:
            raise ValueError("cooldown_hours cannot be shorter than hold_hours")
        if not 0 < self.size <= 1:
            raise ValueError("spot size must be in (0, 1]")
        if self.residual_mode not in ("lagging", "already_led", "none"):
            raise ValueError(f"unsupported residual_mode {self.residual_mode!r}")


class DogeDualLeaderCatchup:
    """Buy a confirmed DOGE lag after synchronous BTC and ETH rallies."""

    def __init__(self, params: DlcParams | None = None):
        self.params = params or DlcParams()
        self._target = 0.0
        self._signal_index: int | None = None
        self._blocked_until = -1

    @property
    def name(self) -> str:
        p = self.params
        confirmation = "confirmed" if p.require_doge_confirmation else "raw"
        return (
            f"doge-dlc-q{p.leader_quantile * 100:g}-h{p.hold_hours}"
            f"-{p.residual_mode}-{confirmation}"
        )

    @property
    def warmup_bars(self) -> int:
        p = self.params
        return max(
            p.leader_history + p.shock_hours + 1,
            p.beta_history + 2,
        )

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
            raise ValueError("DLC checkpoint configuration does not match")
        raw_target = state.get("target")
        raw_signal = state.get("signal_index")
        raw_blocked = state.get("blocked_until")
        if (
            isinstance(raw_target, bool)
            or not isinstance(raw_target, (int, float))
            or float(raw_target) not in (0.0, self.params.size)
        ):
            raise ValueError("invalid DLC checkpoint target")
        if raw_signal is not None and (
            isinstance(raw_signal, bool) or not isinstance(raw_signal, int)
        ):
            raise ValueError("invalid DLC checkpoint signal index")
        if isinstance(raw_blocked, bool) or not isinstance(raw_blocked, int):
            raise ValueError("invalid DLC checkpoint cooldown")
        if (float(raw_target) > 0) != (raw_signal is not None):
            raise ValueError("DLC position and signal index disagree")
        self._target = float(raw_target)
        self._signal_index = raw_signal
        self._blocked_until = raw_blocked

    def on_bar(self, ctx: Context) -> Intent:
        p = self.params
        if self._target > 0:
            if self._signal_index is None:
                raise RuntimeError("DLC position has no signal index")
            if ctx.index - self._signal_index >= p.hold_hours:
                self._target = 0.0
                self._signal_index = None
            return Intent(target=self._target, reason=self.name)

        if ctx.index < self._blocked_until:
            return Intent(target=0.0, reason=self.name)

        btc = ctx.market(BTC_INSTRUMENT, TIMEFRAME)
        eth = ctx.market(ETH_INSTRUMENT, TIMEFRAME)
        if not btc.available or not eth.available:
            return Intent(target=0.0, reason=self.name)
        if btc.bar.ts != ctx.now or eth.bar.ts != ctx.now:
            return Intent(target=0.0, reason=f"{self.name}-unaligned")

        n = self.warmup_bars
        doge_log = np.log(ctx.close(n))
        btc_log = np.log(btc.close(n))
        eth_log = np.log(eth.close(n))
        doge_returns = np.diff(doge_log)
        btc_returns = np.diff(btc_log)
        eth_returns = np.diff(eth_log)
        leader_returns = (btc_returns + eth_returns) / 2.0

        leader_prior = leader_returns[-p.beta_history - 1 : -1]
        doge_prior = doge_returns[-p.beta_history - 1 : -1]
        leader_centered = leader_prior - float(np.mean(leader_prior))
        denominator = float(np.dot(leader_centered, leader_centered))
        if denominator <= 0:
            return Intent(target=0.0, reason=f"{self.name}-zero-beta-variance")
        doge_centered = doge_prior - float(np.mean(doge_prior))
        beta = float(np.dot(doge_centered, leader_centered) / denominator)

        h = p.shock_hours
        doge_impulse = float(doge_log[-1] - doge_log[-h - 1])
        btc_impulse = float(btc_log[-1] - btc_log[-h - 1])
        eth_impulse = float(eth_log[-1] - eth_log[-h - 1])
        residual = doge_impulse - beta * (btc_impulse + eth_impulse) / 2.0

        btc_history = (btc_log[h:-1] - btc_log[: -h - 1])[
            -p.leader_history :
        ]
        eth_history = (eth_log[h:-1] - eth_log[: -h - 1])[
            -p.leader_history :
        ]
        btc_cut = float(np.quantile(btc_history, p.leader_quantile))
        eth_cut = float(np.quantile(eth_history, p.leader_quantile))
        leader_event = btc_impulse > btc_cut and eth_impulse > eth_cut
        confirmation = not p.require_doge_confirmation or doge_returns[-1] > 0
        residual_ok = (
            p.residual_mode == "none"
            or (p.residual_mode == "lagging" and residual <= 0)
            or (p.residual_mode == "already_led" and residual > 0)
        )

        if leader_event and confirmation and residual_ok:
            self._target = p.size
            self._signal_index = ctx.index
            self._blocked_until = ctx.index + p.cooldown_hours
        return Intent(target=self._target, reason=self.name)


class WindowedStrategy:
    """Cold-start strategy state and stay in cash outside one evaluation year."""

    def __init__(
        self,
        factory: Callable[[], ResearchStrategy],
        start_ms: int,
        end_ms: int,
    ):
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


def candidate_factories() -> dict[str, Callable[[], DogeDualLeaderCatchup]]:
    return {
        "main": DogeDualLeaderCatchup,
        "q85": lambda: DogeDualLeaderCatchup(DlcParams(leader_quantile=0.85)),
        "q95": lambda: DogeDualLeaderCatchup(DlcParams(leader_quantile=0.95)),
        "hold8": lambda: DogeDualLeaderCatchup(DlcParams(hold_hours=8)),
        "hold18": lambda: DogeDualLeaderCatchup(DlcParams(hold_hours=18)),
        "leader_only": lambda: DogeDualLeaderCatchup(
            DlcParams(residual_mode="none", require_doge_confirmation=False)
        ),
        "already_led": lambda: DogeDualLeaderCatchup(
            DlcParams(residual_mode="already_led")
        ),
    }


def _run(
    strategy: ResearchStrategy,
    series: Series,
    btc: Series,
    eth: Series,
    slippage_bps: float = BASE_SLIPPAGE_BPS,
) -> RunResult:
    return run_backtest(
        strategy,
        series,
        MarketSpec(INSTRUMENT, "spot"),
        INITIAL_CASH,
        costs=CostModel(fee_bps=BASE_FEE_BPS, slippage_bps=slippage_bps),
        funding=None,
        sizing=Sizing.ON_ENTRY,
        aux=[btc, eth],
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
        "rejections": len(result.rejections),
    }


def _cold_year(
    series: Series,
    btc: Series,
    eth: Series,
    factory: Callable[[], ResearchStrategy],
    year: int,
) -> dict[str, Any]:
    start_ms = to_ms(f"{year}-01-01")
    end_ms = to_ms(f"{year + 1}-01-01")
    result = _run(WindowedStrategy(factory, start_ms, end_ms), series, btc, eth)
    indexes = [
        index
        for index, ts in enumerate(result.timestamps)
        if start_ms <= int(ts) < end_ms
    ]
    if not indexes:
        raise RuntimeError(f"no evaluation bars for {year}")
    timestamps = [result.timestamps[index] for index in indexes]
    equity = [result.equity[index] for index in indexes]
    fills = [fill for fill in result.fills if start_ms <= fill.ts < end_ms]
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
    size: float = DlcParams().size,
    samples: int = SAMPLES,
    seed: int = SEED,
) -> dict[str, float | int]:
    """Random entries matched by entry year, holding bars, size and costs."""
    if not spans:
        return {
            "samples": samples,
            "trades_matched": 0,
            "family_trials": FAMILY_TRIALS,
            "observed": observed,
            "null_p05": 0.0,
            "null_median": 0.0,
            "null_p95": 0.0,
            "p_value": 1.0,
            "family_adjusted_p": 1.0,
        }
    index_of = {int(ts): index for index, ts in enumerate(series.ts)}
    years = np.array([int(from_ms(int(ts))[:4]) for ts in series.ts], dtype=int)
    indexes = np.arange(len(series), dtype=int)
    rng = np.random.default_rng(seed)
    totals = np.ones(samples, dtype=float)
    fee = BASE_FEE_BPS / 10_000
    slip = BASE_SLIPPAGE_BPS / 10_000
    gross_entry = (1.0 + slip) * (1.0 + fee)

    for entry_ts, exit_ts in spans:
        if exit_ts is None:
            raise ValueError("DLC discovery null requires closed episodes")
        entry_index = index_of[int(entry_ts)]
        exit_index = index_of[int(exit_ts)]
        holding_bars = exit_index - entry_index
        if holding_bars < 1:
            raise ValueError("DLC episodes must hold at least one bar")
        valid_end = indexes + holding_bars < len(series)
        valid_volume = np.zeros(len(series), dtype=bool)
        candidates_with_end = indexes[valid_end]
        valid_volume[candidates_with_end] = (
            series.volume[candidates_with_end] > 0
        ) & (series.volume[candidates_with_end + holding_bars] > 0)
        candidates = indexes[
            (years == years[entry_index]) & valid_end & valid_volume
        ]
        if len(candidates) == 0:
            raise ValueError("no year-matched random entry candidates")
        starts = rng.choice(candidates, size=samples, replace=True)
        exits = starts + holding_bars
        gross_exit = (
            series.open[exits]
            / series.open[starts]
            * (1.0 - slip)
            * (1.0 - fee)
        )
        totals *= 1.0 + size * (gross_exit - gross_entry)

    null_returns = totals - 1.0
    exceedances = int(np.sum(null_returns >= observed))
    p_value = (exceedances + 1) / (samples + 1)
    return {
        "samples": samples,
        "trades_matched": len(spans),
        "family_trials": FAMILY_TRIALS,
        "observed": observed,
        "null_p05": float(np.percentile(null_returns, 5)),
        "null_median": float(np.median(null_returns)),
        "null_p95": float(np.percentile(null_returns, 95)),
        "p_value": p_value,
        "family_adjusted_p": sidak_correction(p_value, FAMILY_TRIALS),
    }


def _gate(
    main: dict[str, Any],
    stress: dict[str, Any],
    yearly: list[dict[str, Any]],
    neighbors: dict[str, dict[str, Any]],
    leader_only: dict[str, Any],
    already_led: dict[str, Any],
    random_null: dict[str, float | int],
) -> dict[str, Any]:
    checks = [
        ("15 bps return > 0", main["return"] > 0),
        ("15 bps Sharpe >= 0.50", main["sharpe"] >= 0.50),
        ("MaxDD <= 20%", main["max_drawdown"] <= 0.20),
        ("at least 30 closed trades", main["trades"] >= 30),
        (
            "at least two positive cold-start years",
            sum(row["return"] > 0 for row in yearly) >= 2,
        ),
        ("25 bps/side return > 0", stress["return"] > 0),
        ("return less best closed trade > 0", main["return_less_best_1"] > 0),
        ("episode bootstrap P5 > 0", main["bootstrap_p05"] > 0),
        (
            "all four fixed structural neighbors profitable",
            all(row["return"] > 0 for row in neighbors.values()),
        ),
        (
            "catch-up beats leader-only on mean episode and Sharpe",
            main["mean_episode_return"] > leader_only["mean_episode_return"]
            and main["sharpe"] > leader_only["sharpe"],
        ),
        (
            "catch-up mean episode beats already-led sign placebo",
            main["mean_episode_return"] > already_led["mean_episode_return"],
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
        "checks": [
            {"name": name, "passed": bool(value)} for name, value in checks
        ],
    }


def _pct(value: float) -> str:
    return f"{value * 100:+.2f}%"


def _render(payload: dict[str, Any]) -> str:
    main = payload["main"]
    stress = payload["stress_25bps"]
    null = payload["matched_random_null"]
    lines = [
        "# DOGE 双领导币追赶策略发现结果 (2021-2023)",
        "",
        "> 本进程在数据库层硬截止 2024-01-01; 没有读取 2024、2025 或 2026。",
        "",
        "## 结论",
        "",
        f"**{payload['gate']['verdict']}**",
        "",
        "## 冻结主版本",
        "",
        "| Return | Sharpe | MaxDD | Trades | Mean episode | Less best 1 | 25bps | Bootstrap P5 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"| {_pct(main['return'])} | {main['sharpe']:.2f} | "
        f"{_pct(-main['max_drawdown'])} | {main['trades']} | "
        f"{_pct(main['mean_episode_return'])} | {_pct(main['return_less_best_1'])} | "
        f"{_pct(stress['return'])} | {_pct(main['bootstrap_p05'])} |",
        "",
        "## 冷启动自然年",
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
        "## 固定邻域与机制反证",
        "",
        "| Version | Return | Sharpe | MaxDD | Trades | Mean episode |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name in ("q85", "q95", "hold8", "hold18", "leader_only", "already_led"):
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
        f"- Random P5-P95: `{_pct(float(null['null_p05']))}` .. "
        f"`{_pct(float(null['null_p95']))}`",
        f"- Raw one-sided p: `{float(null['p_value']):.6f}`",
        f"- Sidak-adjusted p ({null['family_trials']} tradable versions): "
        f"`{float(null['family_adjusted_p']):.6f}`",
        "",
        "## 冻结门明细",
        "",
    ]
    lines.extend(
        f"- {'PASS' if row['passed'] else 'FAIL'} - {row['name']}"
        for row in payload["gate"]["checks"]
    )
    lines += [
        "",
        "## Provenance",
        "",
        f"- DOGE fingerprint: `{payload['fingerprints']['doge']}`",
        f"- BTC fingerprint: `{payload['fingerprints']['btc']}`",
        f"- ETH fingerprint: `{payload['fingerprints']['eth']}`",
        f"- Bars: {payload['bars']}",
        f"- Range: `{payload['range']}`",
        "- Costs: 10 bps fee + 5 bps slippage per side; 25 bps stress",
        "- Execution: closed 1h decision, next open fill, 25% spot target",
        "- Protocol: `DUAL_LEADER_CATCHUP_PROTOCOL_2026-07-22.md`",
        "",
    ]
    if not payload["gate"]["passed"]:
        lines += [
            "按预注册规则, 本版本在这里永久停止; 不得打开 2024, 也不得从固定邻域挑选替代品。",
            "",
        ]
    return "\n".join(lines)


def main() -> int:
    end_ms = to_ms(DISCOVERY_END)
    with Store(DB_PATH) as store:
        series = load_series(store, INSTRUMENT, TIMEFRAME, end_ms=end_ms)
        btc = load_series(store, BTC_INSTRUMENT, TIMEFRAME, end_ms=end_ms)
        eth = load_series(store, ETH_INSTRUMENT, TIMEFRAME, end_ms=end_ms)
    markets = {"doge": series, "btc": btc, "eth": eth}
    if any(len(market) == 0 for market in markets.values()):
        raise SystemExit("DLC discovery market data missing")
    if any(int(market.ts[-1]) >= end_ms for market in markets.values()):
        raise RuntimeError("DLC discovery query crossed the frozen 2024 boundary")
    if not np.array_equal(series.ts, btc.ts) or not np.array_equal(series.ts, eth.ts):
        raise RuntimeError("DLC discovery requires an exactly aligned three-market panel")

    factories = candidate_factories()
    results = {
        name: _run(factory(), series, btc, eth)
        for name, factory in factories.items()
    }
    summaries = {name: _summary(result) for name, result in results.items()}
    main_result = results["main"]
    main = summaries["main"]
    stress = _summary(
        _run(
            factories["main"](),
            series,
            btc,
            eth,
            slippage_bps=STRESS_SLIPPAGE_BPS,
        )
    )
    yearly = [
        _cold_year(series, btc, eth, factories["main"], year)
        for year in range(2021, 2024)
    ]
    spans = position_spans(main_result.fills)
    episodes = episode_returns(
        main_result.timestamps,
        main_result.equity,
        main_result.fills,
        main_result.initial_cash,
    )
    observed = float(np.prod(1.0 + np.asarray(episodes, dtype=float)) - 1.0)
    random_null = _matched_random_null(series, spans, observed)
    neighbors = {name: summaries[name] for name in ("q85", "q95", "hold8", "hold18")}
    gate = _gate(
        main,
        stress,
        yearly,
        neighbors,
        summaries["leader_only"],
        summaries["already_led"],
        random_null,
    )
    payload: dict[str, Any] = {
        "study": "doge-dual-leader-catchup-v1",
        "stage": "discovery",
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "query_end_exclusive": DISCOVERY_END,
        "params": asdict(DlcParams()),
        "family_trials": FAMILY_TRIALS,
        "fingerprints": {
            name: series_fingerprint(market) for name, market in markets.items()
        },
        "bars": len(series),
        "range": f"{from_ms(int(series.ts[0]))}..{from_ms(int(series.ts[-1]))}",
        "main": main,
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
