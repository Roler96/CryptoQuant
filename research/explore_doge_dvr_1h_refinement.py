#!/usr/bin/env python
"""Pre-2024 discovery for the DVR 1h execution-resolution refinement (DVR-1H v1).

Direction B of the 1h DOGE-spot study. Does refining the audited daily DVR-Tail20
to 1h resolution improve the already-surviving edge? Frozen in
``DVR_1H_REFINEMENT_PROTOCOL_2026-07-23.md`` before this ran. No new tuning: every
economic parameter is held at the daily DVR's frozen value; the only variable is
execution resolution. Single asset only. Every query has an exclusive 2024 bound.

* baseline_daily: the frozen DogeDvrTail20 on 1d bars (the comparison anchor).
* full_1h:        the same DVR logic on 1h bars, horizon rescaled to 672h (28d).
* hybrid:         daily regime signal (via a 1d as-of aux) with the 20% trailing
                  stop and peak tracking evaluated every 1h on the primary.
"""

from __future__ import annotations

import datetime as dt
import json
import math
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
from cq.research.metrics import compute_metrics, trades_from_fills
from cq.research.split import from_ms, to_ms
from cq.strategy.doge_dvr import DogeDvrConfig, DogeDvrTail20

DB_PATH = "data/cq.db"
INSTRUMENT = "DOGE-USDT"
DISCOVERY_END = "2024-01-01"
INITIAL_CASH = 10_000.0
BASE_FEE_BPS = 10.0
BASE_SLIPPAGE_BPS = 5.0
STRESS_SLIPPAGE_BPS = 15.0
FAMILY_TRIALS = 2
DAILY_HORIZON = 28
HOURLY_HORIZON = DAILY_HORIZON * 24  # 672
OUTPUT_JSON = Path("reports/research/doge_dvr_1h_refinement_discovery.json")
OUTPUT_MD = Path(
    "docs/research/doge-spot/DVR_1H_REFINEMENT_DISCOVERY_RESULTS_2026-07-23.md"
)


class ResearchStrategy(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def warmup_bars(self) -> int: ...

    def reset(self) -> None: ...

    def on_bar(self, ctx: Context) -> Intent: ...


def _regime(closes: np.ndarray) -> tuple[float, float]:
    """Upside-variance share and log momentum over a close window.

    Identical formula to DogeDvrTail20, factored so the hybrid variant reads
    the same regime from daily bars.
    """
    log_returns = np.diff(np.log(closes))
    total_variance = float(np.sum(np.square(log_returns)))
    upside_variance = float(np.sum(np.square(np.maximum(log_returns, 0.0))))
    variance_share = upside_variance / total_variance if total_variance > 0 else 0.5
    momentum = float(math.log(closes[-1] / closes[0]))
    return variance_share, momentum


@dataclass(frozen=True)
class HybridConfig:
    """Daily regime, hourly trailing stop. Economic parameters frozen to DVR."""

    daily_horizon: int = DAILY_HORIZON
    entry_share: float = 0.60
    exit_share: float = 0.45
    trail_drawdown: float = 0.20
    size: float = 0.25

    def __post_init__(self) -> None:
        if self.daily_horizon < 2:
            raise ValueError("daily_horizon must be at least two bars")
        if not 0 <= self.exit_share < self.entry_share <= 1:
            raise ValueError("thresholds must satisfy 0 <= exit < entry <= 1")
        if not 0 < self.trail_drawdown < 1:
            raise ValueError("trail_drawdown must be in (0, 1)")
        if not 0 < self.size <= 1:
            raise ValueError("spot size must be in (0, 1]")


class DogeDvrHybrid:
    """Daily DVR regime with an hourly-resolution trailing stop.

    Entry and regime exit come from the daily bar (via a 1d as-of aux), so their
    timing matches the daily DVR. The 20% trailing stop and its peak are tracked
    on 1h closes and can therefore fire intraday, which is the single change this
    variant isolates.
    """

    def __init__(self, config: HybridConfig | None = None):
        self.config = config or HybridConfig()
        self._target = 0.0
        self._peak_close = 0.0
        self._armed = True

    @property
    def name(self) -> str:
        c = self.config
        return f"doge-dvr-hybrid-d{c.daily_horizon}-trail{c.trail_drawdown * 100:g}"

    @property
    def warmup_bars(self) -> int:
        # Enough 1h bars that the 1d aux carries daily_horizon+1 closed bars.
        return (self.config.daily_horizon + 2) * 24

    def reset(self) -> None:
        self._target = 0.0
        self._peak_close = 0.0
        self._armed = True

    def snapshot_state(self) -> dict[str, object]:
        return {
            "target": self._target,
            "peak_close": self._peak_close,
            "armed": self._armed,
            "config": asdict(self.config),
        }

    def restore_state(self, state: dict[str, object]) -> None:
        if state.get("config") != asdict(self.config):
            raise ValueError("DVR hybrid checkpoint configuration does not match")
        raw_target = state.get("target")
        raw_peak = state.get("peak_close")
        raw_armed = state.get("armed")
        if (
            isinstance(raw_target, bool)
            or not isinstance(raw_target, (int, float))
            or float(raw_target) not in (0.0, self.config.size)
        ):
            raise ValueError("invalid DVR hybrid checkpoint target")
        if (
            isinstance(raw_peak, bool)
            or not isinstance(raw_peak, (int, float))
            or not math.isfinite(float(raw_peak))
            or float(raw_peak) < 0
        ):
            raise ValueError("invalid DVR hybrid checkpoint peak")
        if not isinstance(raw_armed, bool):
            raise ValueError("invalid DVR hybrid checkpoint armed flag")
        self._target = float(raw_target)
        self._peak_close = float(raw_peak)
        self._armed = raw_armed

    def on_bar(self, ctx: Context) -> Intent:
        c = self.config
        daily = ctx.market(INSTRUMENT, "1d")
        if not daily.available:
            return Intent(target=self._target, reason=f"{self.name}-warmup")
        daily_closes = daily.close(c.daily_horizon + 1)
        variance_share, momentum = _regime(daily_closes)
        current = float(ctx.close(1)[-1])
        original_exit = variance_share <= c.exit_share or momentum <= 0

        if self._target > 0:
            self._peak_close = max(self._peak_close, current)
            trail_exit = current <= self._peak_close * (1.0 - c.trail_drawdown)
            if original_exit or trail_exit:
                self._target = 0.0
                self._peak_close = 0.0
                self._armed = bool(original_exit)
        elif not self._armed:
            if original_exit:
                self._armed = True
        elif variance_share >= c.entry_share and momentum > 0:
            self._target = c.size
            self._peak_close = current

        return Intent(target=self._target, reason=self.name)


def _run(
    strategy: ResearchStrategy,
    primary: Series,
    aux: list[Series] | None = None,
    slippage_bps: float = BASE_SLIPPAGE_BPS,
) -> RunResult:
    return run_backtest(
        strategy,
        primary,
        MarketSpec(INSTRUMENT, "spot"),
        INITIAL_CASH,
        costs=CostModel(fee_bps=BASE_FEE_BPS, slippage_bps=slippage_bps),
        funding=None,
        sizing=Sizing.ON_ENTRY,
        aux=aux or [],
    )


def _summary(result: RunResult) -> dict[str, Any]:
    metrics = compute_metrics(
        result.timestamps, result.equity, result.fills, result.initial_cash
    )
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
        "return_less_best_1": (
            (result.final_equity - (net[0] if net else 0.0)) / result.initial_cash - 1.0
        ),
        "fills": len(result.fills),
    }


def _cold_year(
    build: Callable[[], tuple[ResearchStrategy, Series, list[Series]]],
    year: int,
) -> dict[str, Any]:
    """Cold-start a fresh strategy inside one year, in cash outside it."""
    start_ms = to_ms(f"{year}-01-01")
    end_ms = to_ms(f"{year + 1}-01-01")
    strategy, primary, aux = build()
    windowed = _Windowed(strategy, start_ms, end_ms)
    result = _run(windowed, primary, aux)
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


class _Windowed:
    def __init__(self, inner: ResearchStrategy, start_ms: int, end_ms: int):
        self.inner = inner
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


def _beats(variant: dict[str, Any], baseline: dict[str, Any],
           stress: dict[str, Any], baseline_stress: dict[str, Any],
           yearly: list[dict[str, Any]]) -> dict[str, Any]:
    checks = [
        ("15bps return > baseline", variant["return"] > baseline["return"]),
        ("15bps Sharpe > baseline", variant["sharpe"] > baseline["sharpe"]),
        ("MaxDD <= baseline", variant["max_drawdown"] <= baseline["max_drawdown"]),
        (
            "25bps return > 0 and > baseline 25bps",
            stress["return"] > 0 and stress["return"] > baseline_stress["return"],
        ),
        ("at least two positive cold-start years", sum(r["return"] > 0 for r in yearly) >= 2),
        (
            "15bps return > 0 and less-best > 0",
            variant["return"] > 0 and variant["return_less_best_1"] > 0,
        ),
    ]
    passed = all(bool(v) for _, v in checks)
    return {
        "promoted": passed,
        "checks": [{"name": n, "passed": bool(v)} for n, v in checks],
    }


def _pct(value: float) -> str:
    return f"{value * 100:+.2f}%"


def _render(payload: dict[str, Any]) -> str:
    lines = [
        "# DOGE DVR 1h 精化发现结果 (DVR-1H v1, 2021-2023)",
        "",
        "> 数据库层硬截止 2024-01-01; 单资产。零新调参: 经济参数全部冻结为日线 DVR 现值,",
        "> 唯一变量是执行分辨率。1h 变体须证明分辨率带来净改善才晋级。",
        "",
        "## 结论",
        "",
        f"**{payload['verdict']}**",
        "",
        "## 三版本对比 (15bps)",
        "",
        "| Version | Return | Sharpe | MaxDD | UW d | Trades | Hold h | 25bps | LessBest |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in ("baseline_daily", "full_1h", "hybrid"):
        row = payload["versions"][name]
        stress = payload["stress"][name]
        lines.append(
            f"| {name} | {_pct(row['return'])} | {row['sharpe']:.2f} | "
            f"{_pct(-row['max_drawdown'])} | {row['longest_drawdown_days']:.0f} | "
            f"{row['trades']} | {row['mean_hold_hours']:.1f} | "
            f"{_pct(stress['return'])} | {_pct(row['return_less_best_1'])} |"
        )
    lines += ["", "## 冷启动自然年 (15bps)", ""]
    for name in ("baseline_daily", "full_1h", "hybrid"):
        lines += [f"### {name}", "", "| Year | Return | Sharpe | MaxDD | Trades |",
                  "|---:|---:|---:|---:|---:|"]
        for row in payload["yearly"][name]:
            lines.append(
                f"| {row['year']} | {_pct(row['return'])} | {row['sharpe']:.2f} | "
                f"{_pct(-row['max_drawdown'])} | {row['trades']} |"
            )
        lines.append("")
    lines += ["## 晋级门明细", ""]
    for variant in ("full_1h", "hybrid"):
        lines.append(f"### {variant} vs baseline_daily "
                     f"({'PROMOTED' if payload['gate'][variant]['promoted'] else 'not promoted'})")
        lines.extend(
            f"- {'PASS' if row['passed'] else 'FAIL'} — {row['name']}"
            for row in payload["gate"][variant]["checks"]
        )
        lines.append("")
    lines += [
        "## Provenance",
        "",
        f"- DOGE fingerprint (1h): `{payload['fingerprint_1h']}`",
        f"- DOGE fingerprint (1d): `{payload['fingerprint_1d']}`",
        f"- 1h bars: {payload['bars_1h']}, 1d bars: {payload['bars_1d']}",
        f"- Range: `{payload['range']}`",
        "- Costs: 10 bps fee + 5 bps slippage per side; 25 bps stress",
        "- Frozen economics: horizon 28d, entry 0.60, exit 0.45, trail 0.20, size 0.25",
        "- Protocol: `DVR_1H_REFINEMENT_PROTOCOL_2026-07-23.md`",
        "",
    ]
    if payload["verdict"] == "DISCOVERY FAIL":
        lines += [
            "两个 1h 变体都未通过全部晋级门: 1h 分辨率不改善日线 DVR。永久归档 DVR-1H v1,",
            "不读取 2024, 不调参。",
            "",
        ]
    return "\n".join(lines)


def main() -> int:
    end_ms = to_ms(DISCOVERY_END)
    with Store(DB_PATH) as store:
        h1 = load_series(store, INSTRUMENT, "1h", end_ms=end_ms)
        d1 = load_series(store, INSTRUMENT, "1d", end_ms=end_ms)
    if len(h1) == 0 or len(d1) == 0:
        raise SystemExit("DVR-1H discovery market data missing")
    if int(h1.ts[-1]) >= end_ms or int(d1.ts[-1]) >= end_ms:
        raise RuntimeError("DVR-1H discovery query crossed the frozen 2024 boundary")

    def build_daily() -> tuple[ResearchStrategy, Series, list[Series]]:
        return DogeDvrTail20(), d1, []

    def build_full_1h() -> tuple[ResearchStrategy, Series, list[Series]]:
        return DogeDvrTail20(DogeDvrConfig(horizon=HOURLY_HORIZON)), h1, []

    def build_hybrid() -> tuple[ResearchStrategy, Series, list[Series]]:
        return DogeDvrHybrid(), h1, [d1]

    builders = {"baseline_daily": build_daily, "full_1h": build_full_1h, "hybrid": build_hybrid}

    versions: dict[str, dict[str, Any]] = {}
    stress: dict[str, dict[str, Any]] = {}
    yearly: dict[str, list[dict[str, Any]]] = {}
    for name, build in builders.items():
        strat, primary, aux = build()
        versions[name] = _summary(_run(strat, primary, aux))
        strat_s, primary_s, aux_s = build()
        stress[name] = _summary(_run(strat_s, primary_s, aux_s, slippage_bps=STRESS_SLIPPAGE_BPS))
        yearly[name] = [_cold_year(build, year) for year in range(2021, 2024)]

    gate = {
        variant: _beats(
            versions[variant], versions["baseline_daily"],
            stress[variant], stress["baseline_daily"], yearly[variant],
        )
        for variant in ("full_1h", "hybrid")
    }
    promoted = [v for v in ("full_1h", "hybrid") if gate[v]["promoted"]]
    verdict = "DISCOVERY FAIL" if not promoted else f"CANDIDATE: {', '.join(promoted)}"

    payload: dict[str, Any] = {
        "study": "doge-dvr-1h-refinement-v1",
        "stage": "discovery",
        "direction": "B",
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "query_end_exclusive": DISCOVERY_END,
        "family_trials": FAMILY_TRIALS,
        "fingerprint_1h": series_fingerprint(h1),
        "fingerprint_1d": series_fingerprint(d1),
        "bars_1h": len(h1),
        "bars_1d": len(d1),
        "range": f"{from_ms(int(h1.ts[0]))}..{from_ms(int(h1.ts[-1]))}",
        "versions": versions,
        "stress": stress,
        "yearly": yearly,
        "gate": gate,
        "verdict": verdict,
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
