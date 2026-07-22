#!/usr/bin/env python
"""Pre-2024 discovery for three DOGE spot directional-state hypotheses.

The immutable, result-blind candidate definitions and gate are documented in
``DIRECTIONAL_REGIME_DISCOVERY_PROTOCOL_2026-07-22.md``.  This process-level
query ends at 2024-01-01; it cannot expose a later bar to either the strategies
or the reporting code.
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
from cq.research.metrics import compute_metrics, episode_returns, trades_from_fills
from cq.research.split import from_ms, to_ms
from cq.research.stats import bootstrap_trades

DB_PATH = "data/cq.db"
INSTRUMENT = "DOGE-USDT"
TIMEFRAME = "1d"
DISCOVERY_END = "2024-01-01"
INITIAL_CASH = 10_000.0
BASE_FEE_BPS = 10.0
BASE_SLIPPAGE_BPS = 5.0
STRESS_SLIPPAGE_BPS = 15.0
SEED = 20260722
OUTPUT_JSON = Path("reports/research/doge_directional_regimes_discovery.json")
OUTPUT_MD = Path(
    "docs/research/doge-spot/DIRECTIONAL_REGIME_DISCOVERY_RESULTS_2026-07-22.md"
)


class ResearchStrategy(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def warmup_bars(self) -> int: ...

    def reset(self) -> None: ...

    def on_bar(self, ctx: Context) -> Intent: ...


@dataclass(frozen=True)
class DvrParams:
    horizon: int = 28
    entry_share: float = 0.60
    exit_share: float = 0.45
    size: float = 1.0

    def __post_init__(self) -> None:
        if self.horizon < 2:
            raise ValueError("horizon must be at least two bars")
        if not 0 <= self.exit_share < self.entry_share <= 1:
            raise ValueError("DVR thresholds must satisfy 0 <= exit < entry <= 1")
        if not 0 < self.size <= 1:
            raise ValueError("spot size must be in (0, 1]")


class DogeDirectionalVariance:
    """Long only when upside returns dominate trailing realised variance."""

    def __init__(self, params: DvrParams | None = None):
        self.params = params or DvrParams()
        self._target = 0.0

    @property
    def name(self) -> str:
        return f"doge-dvr-{self.params.horizon}d"

    @property
    def warmup_bars(self) -> int:
        return self.params.horizon + 1

    def reset(self) -> None:
        self._target = 0.0

    def snapshot_state(self) -> dict[str, object]:
        return {"target": self._target, "params": asdict(self.params)}

    def on_bar(self, ctx: Context) -> Intent:
        close = ctx.close(self.warmup_bars)
        log_returns = np.diff(np.log(close))
        total_variance = float(np.sum(np.square(log_returns)))
        upside_variance = float(
            np.sum(np.square(np.maximum(log_returns, 0.0)))
        )
        share = upside_variance / total_variance if total_variance > 0 else 0.5
        momentum = float(math.log(close[-1] / close[0]))

        if self._target == 0.0:
            if share >= self.params.entry_share and momentum > 0:
                self._target = self.params.size
        elif share <= self.params.exit_share or momentum <= 0:
            self._target = 0.0
        return Intent(target=self._target, reason=self.name)


@dataclass(frozen=True)
class MpeParams:
    horizons: tuple[int, int, int] = (8, 32, 128)
    size: float = 1.0

    def __post_init__(self) -> None:
        if len(self.horizons) != 3 or tuple(sorted(set(self.horizons))) != self.horizons:
            raise ValueError("MPE requires three unique increasing horizons")
        if self.horizons[0] < 2:
            raise ValueError("MPE horizons must be at least two bars")
        if not 0 < self.size <= 1:
            raise ValueError("spot size must be in (0, 1]")


class DogeMomentumPersistenceEnsemble:
    """Equal-weight positive time-series momentum sleeves."""

    def __init__(self, params: MpeParams | None = None):
        self.params = params or MpeParams()
        self._target = 0.0

    @property
    def name(self) -> str:
        horizons = "-".join(str(value) for value in self.params.horizons)
        return f"doge-mpe-{horizons}d"

    @property
    def warmup_bars(self) -> int:
        return max(self.params.horizons) + 1

    def reset(self) -> None:
        self._target = 0.0

    def snapshot_state(self) -> dict[str, object]:
        return {"target": self._target, "params": asdict(self.params)}

    def on_bar(self, ctx: Context) -> Intent:
        close = ctx.close(self.warmup_bars)
        bullish = sum(
            float(close[-1]) > float(close[-horizon - 1])
            for horizon in self.params.horizons
        )
        self._target = self.params.size * bullish / len(self.params.horizons)
        return Intent(target=self._target, reason=self.name)


@dataclass(frozen=True)
class DebParams:
    horizon: int = 28
    exit_bars: int = 10
    min_efficiency: float = 0.20
    size: float = 1.0

    def __post_init__(self) -> None:
        if self.horizon < 2 or not 2 <= self.exit_bars < self.horizon:
            raise ValueError("DEB needs 2 <= exit_bars < horizon")
        if not 0 < self.min_efficiency < 1:
            raise ValueError("min_efficiency must be in (0, 1)")
        if not 0 < self.size <= 1:
            raise ValueError("spot size must be in (0, 1]")


class DogeDirectionalEfficiencyBreakout:
    """Break out only when net displacement dominates the travelled path."""

    def __init__(self, params: DebParams | None = None):
        self.params = params or DebParams()
        self._target = 0.0

    @property
    def name(self) -> str:
        return f"doge-deb-{self.params.horizon}-{self.params.exit_bars}d"

    @property
    def warmup_bars(self) -> int:
        return self.params.horizon + 1

    def reset(self) -> None:
        self._target = 0.0

    def snapshot_state(self) -> dict[str, object]:
        return {"target": self._target, "params": asdict(self.params)}

    def on_bar(self, ctx: Context) -> Intent:
        p = self.params
        close = ctx.close(self.warmup_bars)
        log_returns = np.diff(np.log(close))
        travelled = float(np.sum(np.abs(log_returns)))
        efficiency = float(np.sum(log_returns)) / travelled if travelled > 0 else 0.0
        current = float(close[-1])

        if self._target == 0.0:
            prior_high = float(np.max(ctx.high(p.horizon + 1)[:-1]))
            if current > prior_high and efficiency >= p.min_efficiency:
                self._target = p.size
        else:
            prior_low = float(np.min(ctx.low(p.exit_bars + 1)[:-1]))
            if current < prior_low or efficiency <= 0:
                self._target = 0.0
        return Intent(target=self._target, reason=self.name)


class WindowedStrategy:
    """Cold-start an inner strategy and keep cash outside one evaluation span."""

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


def candidate_factories() -> dict[str, Callable[[], ResearchStrategy]]:
    return {
        "dvr21": lambda: DogeDirectionalVariance(DvrParams(horizon=21)),
        "dvr28": DogeDirectionalVariance,
        "dvr42": lambda: DogeDirectionalVariance(DvrParams(horizon=42)),
        "mpe_fast": lambda: DogeMomentumPersistenceEnsemble(
            MpeParams(horizons=(6, 24, 96))
        ),
        "mpe_main": DogeMomentumPersistenceEnsemble,
        "mpe_slow": lambda: DogeMomentumPersistenceEnsemble(
            MpeParams(horizons=(12, 48, 192))
        ),
        "deb_fast": lambda: DogeDirectionalEfficiencyBreakout(
            DebParams(horizon=21, exit_bars=7)
        ),
        "deb_main": DogeDirectionalEfficiencyBreakout,
        "deb_slow": lambda: DogeDirectionalEfficiencyBreakout(
            DebParams(horizon=42, exit_bars=14)
        ),
    }


def _run(
    strategy: ResearchStrategy,
    series: Series,
    slippage_bps: float = BASE_SLIPPAGE_BPS,
) -> RunResult:
    return run_backtest(
        strategy,
        series,
        MarketSpec(INSTRUMENT, "spot"),
        INITIAL_CASH,
        costs=CostModel(fee_bps=BASE_FEE_BPS, slippage_bps=slippage_bps),
        sizing=Sizing.ON_ENTRY,
    )


def _summary(result: RunResult) -> dict[str, Any]:
    metrics = compute_metrics(
        result.timestamps, result.equity, result.fills, result.initial_cash
    )
    episodes = episode_returns(
        result.timestamps, result.equity, result.fills, result.initial_cash
    )
    bootstrap = bootstrap_trades(episodes, samples=10_000, seed=SEED)
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
        "return_less_best_1": (
            (result.final_equity - (net[0] if net else 0.0)) / result.initial_cash - 1.0
        ),
        "episode_count": len(episodes),
        "bootstrap_probability_of_loss": bootstrap.probability_of_loss,
        "bootstrap_p05": bootstrap.percentile_05,
        "fills": len(result.fills),
        "rejections": len(result.rejections),
    }


def _cold_year(
    series: Series,
    factory: Callable[[], ResearchStrategy],
    year: int,
) -> dict[str, Any]:
    result = _run(
        WindowedStrategy(
            factory,
            to_ms(f"{year}-01-01"),
            to_ms(f"{year + 1}-01-01"),
        ),
        series,
    )
    start_ms = to_ms(f"{year}-01-01")
    end_ms = to_ms(f"{year + 1}-01-01")
    indexes = [
        index
        for index, ts in enumerate(result.timestamps)
        if start_ms <= int(ts) < end_ms
    ]
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


def _gate(
    main: dict[str, Any],
    stress: dict[str, Any],
    yearly: list[dict[str, Any]],
    neighbors: list[dict[str, Any]],
) -> dict[str, Any]:
    checks = [
        ("15 bps return > 0", main["return"] > 0),
        ("15 bps Sharpe >= 0.40", main["sharpe"] >= 0.40),
        ("MaxDD <= 55%", main["max_drawdown"] <= 0.55),
        (
            "at least two positive cold-start years",
            sum(row["return"] > 0 for row in yearly) >= 2,
        ),
        ("25 bps/side return > 0", stress["return"] > 0),
        ("return less best closed trade > 0", main["return_less_best_1"] > 0),
        ("at least six closed trades", main["trades"] >= 6),
        (
            "both fixed structural neighbors profitable",
            all(row["return"] > 0 for row in neighbors),
        ),
    ]
    return {
        "passed": all(bool(passed) for _, passed in checks),
        "checks": [
            {"name": name, "passed": bool(passed)} for name, passed in checks
        ],
    }


def _pct(value: float) -> str:
    return f"{value * 100:+.2f}%"


def _render(payload: dict[str, Any]) -> str:
    lines = [
        "# DOGE 方向性状态策略发现结果 (2021-2023)",
        "",
        "> 本进程只查询 2024-01-01 以前的数据; 2024、2025、2026 未读取。",
        "",
        "## 主候选",
        "",
        "| Candidate | Return | Sharpe | MaxDD | Trades | Less best 1 | 25bps return | Gate |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for family in ("dvr", "mpe", "deb"):
        row = payload["families"][family]
        main = row["main"]
        lines.append(
            f"| {row['main_name']} | {_pct(main['return'])} | {main['sharpe']:.2f} | "
            f"{_pct(-main['max_drawdown'])} | {main['trades']} | "
            f"{_pct(main['return_less_best_1'])} | {_pct(row['stress_25bps']['return'])} | "
            f"{'PASS' if row['gate']['passed'] else 'FAIL'} |"
        )

    lines += [
        "",
        "## 冷启动自然年",
        "",
        "| Candidate | 2021 | 2022 | 2023 |",
        "|---|---:|---:|---:|",
    ]
    for family in ("dvr", "mpe", "deb"):
        row = payload["families"][family]
        annual = " | ".join(_pct(item["return"]) for item in row["yearly"])
        lines.append(f"| {row['main_name']} | {annual} |")

    lines += [
        "",
        "## 固定结构邻域",
        "",
        "| Candidate | Return | Sharpe | MaxDD | Trades |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, row in payload["all_candidates"].items():
        if name in {"dvr28", "mpe_main", "deb_main"}:
            continue
        lines.append(
            f"| {name} | {_pct(row['return'])} | {row['sharpe']:.2f} | "
            f"{_pct(-row['max_drawdown'])} | {row['trades']} |"
        )

    lines += [
        "",
        "## 发现门明细",
        "",
    ]
    for family in ("dvr", "mpe", "deb"):
        row = payload["families"][family]
        lines.append(f"### {row['main_name']}")
        lines.append("")
        lines.extend(
            f"- {'PASS' if check['passed'] else 'FAIL'} - {check['name']}"
            for check in row["gate"]["checks"]
        )
        lines.append("")

    lines += [
        "## Provenance",
        "",
        f"- Source fingerprint: `{payload['source_fingerprint']}`",
        f"- Aggregated fingerprint: `{payload['data_fingerprint']}`",
        f"- Bars: {payload['bars']}",
        f"- Range: `{payload['range']}`",
        "- Query hard end: `2024-01-01 00:00 UTC` (exclusive)",
        "- Costs: 10 bps fee + 5 bps slippage per side; 25 bps stress",
        "- Execution: closed daily bar decision, next daily open fill, ON_ENTRY",
        "- Registered attempts: 9",
        "",
    ]
    return "\n".join(lines)


def _source_fingerprint(series: Series) -> str:
    return series_fingerprint(series)


def main() -> int:
    end_ms = to_ms(DISCOVERY_END)
    with Store(DB_PATH) as store:
        source = load_series(
            store,
            INSTRUMENT,
            "1h",
            end_ms=end_ms,
        )
        series = load_series(
            store,
            INSTRUMENT,
            TIMEFRAME,
            end_ms=end_ms,
        )
    if len(source) == 0 or len(series) == 0:
        raise SystemExit("DOGE-USDT discovery data missing")
    if int(source.ts[-1]) >= end_ms or int(series.ts[-1]) >= end_ms:
        raise RuntimeError("discovery query crossed the frozen 2024 boundary")

    factories = candidate_factories()
    summaries = {
        name: _summary(_run(factory(), series))
        for name, factory in factories.items()
    }
    definitions = {
        "dvr": ("dvr28", ("dvr21", "dvr42")),
        "mpe": ("mpe_main", ("mpe_fast", "mpe_slow")),
        "deb": ("deb_main", ("deb_fast", "deb_slow")),
    }
    families: dict[str, Any] = {}
    for family, (main_name, neighbor_names) in definitions.items():
        factory = factories[main_name]
        main_summary = summaries[main_name]
        stress = _summary(
            _run(factory(), series, slippage_bps=STRESS_SLIPPAGE_BPS)
        )
        yearly = [_cold_year(series, factory, year) for year in range(2021, 2024)]
        neighbors = [summaries[name] for name in neighbor_names]
        families[family] = {
            "main_name": main_name,
            "main": main_summary,
            "stress_25bps": stress,
            "yearly": yearly,
            "neighbors": dict(zip(neighbor_names, neighbors, strict=True)),
            "gate": _gate(main_summary, stress, yearly, neighbors),
        }

    payload: dict[str, Any] = {
        "study": "doge-directional-regimes-v1",
        "stage": "discovery",
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "query_end_exclusive": DISCOVERY_END,
        "registered_attempts": 9,
        "source_fingerprint": _source_fingerprint(source),
        "data_fingerprint": series_fingerprint(series),
        "bars": len(series),
        "range": f"{from_ms(int(series.ts[0]))}..{from_ms(int(series.ts[-1]))}",
        "all_candidates": summaries,
        "families": families,
        "survivors": [
            row["main_name"] for row in families.values() if row["gate"]["passed"]
        ],
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
