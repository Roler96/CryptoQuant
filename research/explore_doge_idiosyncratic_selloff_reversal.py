#!/usr/bin/env python
"""Pre-2024 discovery for the frozen DOGE idiosyncratic selloff reversal.

The formula and all gates were frozen in
``IDIOSYNCRATIC_SELLOFF_REVERSAL_PROTOCOL_2026-07-22.md`` before this runner
was executed. Every market query has an exclusive 2024 boundary.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np

from cq.context import Context, series_fingerprint
from cq.core.types import Intent
from cq.data.feed import load_series
from cq.data.store import Store
from cq.research.metrics import episode_returns, position_spans
from cq.research.split import to_ms
from research.explore_doge_dual_leader_catchup import (
    BTC_INSTRUMENT,
    DB_PATH,
    DISCOVERY_END,
    ETH_INSTRUMENT,
    FAMILY_TRIALS,
    INSTRUMENT,
    STRESS_SLIPPAGE_BPS,
    TIMEFRAME,
    _cold_year,
    _matched_random_null,
    _run,
    _summary,
)

OUTPUT_JSON = Path("reports/research/doge_idiosyncratic_selloff_reversal_discovery.json")
OUTPUT_MD = Path(
    "docs/research/doge-spot/"
    "IDIOSYNCRATIC_SELLOFF_REVERSAL_DISCOVERY_RESULTS_2026-07-22.md"
)

ResidualMode = Literal["tail", "none"]


@dataclass(frozen=True)
class IsrParams:
    """Frozen ISR formula and event-state parameters."""

    shock_hours: int = 6
    beta_history: int = 2_160
    residual_quantile: float = 0.05
    hold_hours: int = 12
    cooldown_after_exit: int = 48
    size: float = 0.25
    residual_mode: ResidualMode = "tail"
    require_market_nonnegative: bool = True
    require_confirmation: bool = True

    def __post_init__(self) -> None:
        if self.shock_hours < 1:
            raise ValueError("shock_hours must be positive")
        if self.beta_history < self.shock_hours:
            raise ValueError("beta_history cannot be shorter than shock_hours")
        if not 0 < self.residual_quantile < 1:
            raise ValueError("residual_quantile must be in (0, 1)")
        if self.hold_hours < 1:
            raise ValueError("hold_hours must be positive")
        if self.cooldown_after_exit < 0:
            raise ValueError("cooldown_after_exit cannot be negative")
        if not 0 < self.size <= 1:
            raise ValueError("spot size must be in (0, 1]")
        if self.residual_mode not in ("tail", "none"):
            raise ValueError(f"unsupported residual mode {self.residual_mode!r}")


class DogeIdiosyncraticSelloffReversal:
    """Buy a confirmed DOGE-specific selloff while BTC/ETH are non-negative."""

    def __init__(self, params: IsrParams | None = None):
        self.params = params or IsrParams()
        self._target = 0.0
        self._signal_index: int | None = None
        self._blocked_until = -1

    @property
    def name(self) -> str:
        p = self.params
        market = "market-up" if p.require_market_nonnegative else "any-market"
        confirmation = "confirmed" if p.require_confirmation else "raw"
        return (
            f"doge-isr-q{p.residual_quantile * 100:g}-h{p.hold_hours}-"
            f"{p.residual_mode}-{market}-{confirmation}"
        )

    @property
    def warmup_bars(self) -> int:
        return self.params.beta_history + self.params.shock_hours + 1

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
            raise ValueError("ISR checkpoint configuration does not match")
        raw_target = state.get("target")
        raw_signal = state.get("signal_index")
        raw_blocked = state.get("blocked_until")
        if (
            isinstance(raw_target, bool)
            or not isinstance(raw_target, (int, float))
            or float(raw_target) not in (0.0, self.params.size)
        ):
            raise ValueError("invalid ISR checkpoint target")
        if raw_signal is not None and (
            isinstance(raw_signal, bool) or not isinstance(raw_signal, int)
        ):
            raise ValueError("invalid ISR checkpoint signal index")
        if isinstance(raw_blocked, bool) or not isinstance(raw_blocked, int):
            raise ValueError("invalid ISR checkpoint cooldown")
        if (float(raw_target) > 0) != (raw_signal is not None):
            raise ValueError("ISR position and signal index disagree")
        self._target = float(raw_target)
        self._signal_index = raw_signal
        self._blocked_until = raw_blocked

    def on_bar(self, ctx: Context) -> Intent:
        p = self.params
        if self._target > 0.0:
            if self._signal_index is None:
                raise RuntimeError("ISR position has no signal index")
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
        doge_returns = np.diff(np.log(ctx.close(n)))
        btc_returns = np.diff(np.log(btc.close(n)))
        eth_returns = np.diff(np.log(eth.close(n)))
        market_returns = (btc_returns + eth_returns) / 2.0

        h = p.shock_hours
        doge_calibration = doge_returns[:-h]
        market_calibration = market_returns[:-h]
        if len(doge_calibration) != p.beta_history:
            raise RuntimeError("ISR calibration window has the wrong length")
        market_centered = market_calibration - float(np.mean(market_calibration))
        denominator = float(np.dot(market_centered, market_centered))
        if denominator <= 0.0 or not np.isfinite(denominator):
            return Intent(target=0.0, reason=f"{self.name}-zero-market-variance")
        doge_centered = doge_calibration - float(np.mean(doge_calibration))
        beta = float(np.dot(doge_centered, market_centered) / denominator)
        if not np.isfinite(beta):
            return Intent(target=0.0, reason=f"{self.name}-non-finite-beta")

        kernel = np.ones(h, dtype=float)
        past_doge = np.convolve(doge_calibration, kernel, mode="valid")
        past_market = np.convolve(market_calibration, kernel, mode="valid")
        past_residual = past_doge - beta * past_market
        residual_cut = float(
            np.quantile(past_residual, p.residual_quantile, method="linear")
        )
        doge_impulse = float(np.sum(doge_returns[-h:]))
        market_impulse = float(np.sum(market_returns[-h:]))
        current_residual = doge_impulse - beta * market_impulse

        residual_ok = p.residual_mode == "none" or current_residual < residual_cut
        market_ok = not p.require_market_nonnegative or market_impulse >= 0.0
        confirmation = not p.require_confirmation or doge_returns[-1] > 0.0
        if residual_ok and doge_impulse < 0.0 and market_ok and confirmation:
            self._target = p.size
            self._signal_index = ctx.index
            self._blocked_until = (
                ctx.index + p.hold_hours + p.cooldown_after_exit
            )
        return Intent(target=self._target, reason=self.name)


def candidate_factories() -> dict[str, Callable[[], DogeIdiosyncraticSelloffReversal]]:
    return {
        "main": DogeIdiosyncraticSelloffReversal,
        "q025": lambda: DogeIdiosyncraticSelloffReversal(
            IsrParams(residual_quantile=0.025)
        ),
        "q10": lambda: DogeIdiosyncraticSelloffReversal(
            IsrParams(residual_quantile=0.10)
        ),
        "hold6": lambda: DogeIdiosyncraticSelloffReversal(IsrParams(hold_hours=6)),
        "hold24": lambda: DogeIdiosyncraticSelloffReversal(IsrParams(hold_hours=24)),
        "no_market_filter": lambda: DogeIdiosyncraticSelloffReversal(
            IsrParams(require_market_nonnegative=False)
        ),
        "plain_reversal": lambda: DogeIdiosyncraticSelloffReversal(
            IsrParams(residual_mode="none", require_market_nonnegative=False)
        ),
    }


def _gate(
    main: dict[str, Any],
    stress: dict[str, Any],
    yearly: list[dict[str, Any]],
    neighbors: dict[str, dict[str, Any]],
    no_market: dict[str, Any],
    plain: dict[str, Any],
    random_null: dict[str, float | int],
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
            "all four fixed structural neighbors profitable",
            all(row["return"] > 0 for row in neighbors.values()),
        ),
        (
            "main beats plain reversal on Sharpe and mean episode",
            main["sharpe"] > plain["sharpe"]
            and main["mean_episode_return"] > plain["mean_episode_return"],
        ),
        (
            "main mean episode beats no-market-filter ablation",
            main["mean_episode_return"] > no_market["mean_episode_return"],
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
        "# DOGE 特异性卖压反转发现结果 (ISR v1, 2021-2023)",
        "",
        "> 本进程在数据库查询层排他硬截止 2024-01-01; 未读取后续年度。",
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
        "## 固定邻域与机制消融",
        "",
        "| Version | Return | Sharpe | MaxDD | Trades | Mean episode |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name in (
        "q025",
        "q10",
        "hold6",
        "hold24",
        "no_market_filter",
        "plain_reversal",
    ):
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
        f"- {'PASS' if row['passed'] else 'FAIL'} — {row['name']}"
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
        "- Protocol: `IDIOSYNCRATIC_SELLOFF_REVERSAL_PROTOCOL_2026-07-22.md`",
        "",
    ]
    if not payload["gate"]["passed"]:
        lines += [
            "按冻结规则, ISR v1 在 discovery 永久停止; 不读取2024, 也不从邻域替补。",
            "",
        ]
    return "\n".join(lines)


def main() -> int:
    end_ms = to_ms(DISCOVERY_END)
    with Store(DB_PATH) as store:
        doge = load_series(store, INSTRUMENT, TIMEFRAME, end_ms=end_ms)
        btc = load_series(store, BTC_INSTRUMENT, TIMEFRAME, end_ms=end_ms)
        eth = load_series(store, ETH_INSTRUMENT, TIMEFRAME, end_ms=end_ms)
    markets = {"doge": doge, "btc": btc, "eth": eth}
    if any(len(market) == 0 for market in markets.values()):
        raise SystemExit("ISR discovery market data missing")
    if any(int(market.ts[-1]) >= end_ms for market in markets.values()):
        raise RuntimeError("ISR discovery query crossed the frozen 2024 boundary")
    if not np.array_equal(doge.ts, btc.ts) or not np.array_equal(doge.ts, eth.ts):
        raise RuntimeError("ISR discovery requires an exactly aligned three-market panel")

    factories = candidate_factories()
    results = {name: _run(factory(), doge, btc, eth) for name, factory in factories.items()}
    summaries = {name: _summary(result) for name, result in results.items()}
    main_result = results["main"]
    main_summary = summaries["main"]
    stress = _summary(
        _run(
            factories["main"](),
            doge,
            btc,
            eth,
            slippage_bps=STRESS_SLIPPAGE_BPS,
        )
    )
    yearly = [
        _cold_year(doge, btc, eth, factories["main"], year)
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
    random_null = _matched_random_null(doge, spans, observed)
    neighbors = {
        name: summaries[name] for name in ("q025", "q10", "hold6", "hold24")
    }
    gate = _gate(
        main_summary,
        stress,
        yearly,
        neighbors,
        summaries["no_market_filter"],
        summaries["plain_reversal"],
        random_null,
    )
    payload = {
        "study": "DOGE_ISR_V1",
        "protocol_frozen_at": "2026-07-22 09:00 UTC",
        "discovery_end_exclusive": DISCOVERY_END,
        "family_trials": FAMILY_TRIALS,
        "params": asdict(IsrParams()),
        "bars": len(doge),
        "range": f"{int(doge.ts[0])} .. {int(doge.ts[-1])}",
        "fingerprints": {
            "doge": series_fingerprint(doge),
            "btc": series_fingerprint(btc),
            "eth": series_fingerprint(eth),
        },
        "main": main_summary,
        "stress_25bps": stress,
        "yearly": yearly,
        "variants": {name: summaries[name] for name in factories if name != "main"},
        "matched_random_null": random_null,
        "gate": gate,
    }
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    OUTPUT_MD.write_text(_render(payload), encoding="utf-8")
    print(_render(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
