#!/usr/bin/env python
"""Pre-2024 discovery for the frozen DOGE perpetual-premium hypothesis."""

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
SWAP_INSTRUMENT = "DOGE-USDT-SWAP"
TIMEFRAME = "4h"
DISCOVERY_END = "2024-01-01"
INITIAL_CASH = 10_000.0
BASE_FEE_BPS = 10.0
BASE_SLIPPAGE_BPS = 5.0
STRESS_SLIPPAGE_BPS = 15.0
SAMPLES = 10_000
SEED = 20260722
FAMILY_TRIALS = 5
OUTPUT_JSON = Path(
    "reports/research/doge_perpetual_premium_confirmation_discovery.json"
)
OUTPUT_MD = Path(
    "docs/research/doge-spot/"
    "PERPETUAL_PREMIUM_CONFIRMATION_DISCOVERY_RESULTS_2026-07-22.md"
)


class ResearchStrategy(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def warmup_bars(self) -> int: ...

    def reset(self) -> None: ...

    def on_bar(self, ctx: Context) -> Intent: ...


@dataclass(frozen=True)
class PpcParams:
    """Frozen perpetual-premium confirmation parameters."""

    premium_history: int = 180
    premium_block: int = 6
    premium_entry: float = 1.0
    premium_exit: float = 0.0
    momentum_bars: int = 42
    size: float = 0.25
    use_premium: bool = True
    use_momentum: bool = True

    def __post_init__(self) -> None:
        if self.premium_history < 2:
            raise ValueError("premium_history must be at least two bars")
        if self.premium_block < 1:
            raise ValueError("premium_block must be positive")
        if self.premium_entry <= self.premium_exit:
            raise ValueError("premium entry must exceed exit")
        if self.momentum_bars < 1:
            raise ValueError("momentum_bars must be positive")
        if not 0 < self.size <= 1:
            raise ValueError("spot size must be in (0, 1]")
        if not self.use_premium and not self.use_momentum:
            raise ValueError("PPC must use at least one state variable")


class DogePerpetualPremiumConfirmation:
    """Hold DOGE spot only in a positive-premium, positive-momentum state."""

    def __init__(self, params: PpcParams | None = None):
        self.params = params or PpcParams()
        self._target = 0.0

    @property
    def name(self) -> str:
        p = self.params
        states = (
            "joint"
            if p.use_premium and p.use_momentum
            else "premium"
            if p.use_premium
            else "momentum"
        )
        return (
            f"doge-ppc-{states}-hist{p.premium_history}"
            f"-entry{p.premium_entry:g}"
        )

    @property
    def warmup_bars(self) -> int:
        p = self.params
        return max(
            p.premium_history + p.premium_block,
            p.momentum_bars + 1,
        )

    def reset(self) -> None:
        self._target = 0.0

    def snapshot_state(self) -> dict[str, object]:
        return {"target": self._target, "params": asdict(self.params)}

    def restore_state(self, state: dict[str, object]) -> None:
        if state.get("params") != asdict(self.params):
            raise ValueError("PPC checkpoint configuration does not match")
        raw_target = state.get("target")
        if (
            isinstance(raw_target, bool)
            or not isinstance(raw_target, (int, float))
            or float(raw_target) not in (0.0, self.params.size)
        ):
            raise ValueError("invalid PPC checkpoint target")
        self._target = float(raw_target)

    def on_bar(self, ctx: Context) -> Intent:
        p = self.params
        swap = ctx.market(SWAP_INSTRUMENT, TIMEFRAME)
        if not swap.available or swap.bar.ts != ctx.now:
            return Intent(target=self._target, reason=f"{self.name}-unaligned")

        n = self.warmup_bars
        spot_close = ctx.close(n)
        swap_close = swap.close(n)
        basis = np.log(swap_close / spot_close)
        baseline = basis[-p.premium_history - p.premium_block : -p.premium_block]
        current = basis[-p.premium_block :]
        baseline_median = float(np.median(baseline))
        mad = float(np.median(np.abs(baseline - baseline_median)))
        premium_available = mad > 0
        premium_score = (
            (float(np.median(current)) - baseline_median) / mad
            if premium_available
            else 0.0
        )
        momentum = float(
            np.log(spot_close[-1] / spot_close[-p.momentum_bars - 1])
        )

        premium_entry = not p.use_premium or (
            premium_available and premium_score >= p.premium_entry
        )
        momentum_entry = not p.use_momentum or momentum > 0
        premium_exit = p.use_premium and (
            not premium_available or premium_score <= p.premium_exit
        )
        momentum_exit = p.use_momentum and momentum <= 0

        if self._target == 0.0:
            if premium_entry and momentum_entry:
                self._target = p.size
        elif premium_exit or momentum_exit:
            self._target = 0.0
        return Intent(target=self._target, reason=self.name)


class WindowedStrategy:
    """Cold-start strategy state and remain cash outside one evaluation year."""

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


def candidate_factories() -> dict[
    str, Callable[[], DogePerpetualPremiumConfirmation]
]:
    return {
        "main": DogePerpetualPremiumConfirmation,
        "history120": lambda: DogePerpetualPremiumConfirmation(
            PpcParams(premium_history=120)
        ),
        "history270": lambda: DogePerpetualPremiumConfirmation(
            PpcParams(premium_history=270)
        ),
        "entry05": lambda: DogePerpetualPremiumConfirmation(
            PpcParams(premium_entry=0.5)
        ),
        "entry15": lambda: DogePerpetualPremiumConfirmation(
            PpcParams(premium_entry=1.5)
        ),
        "momentum_only": lambda: DogePerpetualPremiumConfirmation(
            PpcParams(use_premium=False)
        ),
        "premium_only": lambda: DogePerpetualPremiumConfirmation(
            PpcParams(use_momentum=False)
        ),
    }


def _run(
    strategy: ResearchStrategy,
    series: Series,
    swap: Series,
    slippage_bps: float = BASE_SLIPPAGE_BPS,
) -> RunResult:
    return run_backtest(
        strategy,
        series,
        MarketSpec(INSTRUMENT, "spot"),
        INITIAL_CASH,
        costs=CostModel(fee_bps=BASE_FEE_BPS, slippage_bps=slippage_bps),
        funding=None,
        aux=[swap],
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
        "rejections": len(result.rejections),
        "open_position_at_end": len(result.fills) % 2 == 1,
    }


def _cold_year(
    series: Series,
    swap: Series,
    factory: Callable[[], ResearchStrategy],
    year: int,
) -> dict[str, Any]:
    start_ms = to_ms(f"{year}-01-01")
    end_ms = to_ms(f"{year + 1}-01-01")
    result = _run(WindowedStrategy(factory, start_ms, end_ms), series, swap)
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
    size: float = PpcParams().size,
    samples: int = SAMPLES,
    seed: int = SEED,
) -> dict[str, float | int]:
    """Random entries matched by year, holding bars, open state, size and costs."""
    if not spans:
        return {
            "samples": samples,
            "episodes_matched": 0,
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
    last = len(series) - 1
    rng = np.random.default_rng(seed)
    totals = np.ones(samples, dtype=float)
    fee = BASE_FEE_BPS / 10_000
    slip = BASE_SLIPPAGE_BPS / 10_000
    gross_entry = (1.0 + slip) * (1.0 + fee)

    for entry_ts, exit_ts in spans:
        entry_index = index_of[int(entry_ts)]
        is_open = exit_ts is None
        exit_index = last if is_open else index_of[int(exit_ts)]
        holding_bars = exit_index - entry_index
        if holding_bars < 1:
            raise ValueError("PPC episodes must hold at least one bar")
        valid_end = indexes + holding_bars <= last
        valid_volume = np.zeros(len(series), dtype=bool)
        candidates_with_end = indexes[valid_end]
        valid_volume[candidates_with_end] = series.volume[candidates_with_end] > 0
        if not is_open:
            valid_volume[candidates_with_end] &= (
                series.volume[candidates_with_end + holding_bars] > 0
            )
        candidates = indexes[
            (years == years[entry_index]) & valid_end & valid_volume
        ]
        if len(candidates) == 0:
            raise ValueError("no year-matched random entry candidates")
        starts = rng.choice(candidates, size=samples, replace=True)
        ends = starts + holding_bars
        if is_open:
            gross_exit = series.close[ends] / series.open[starts]
        else:
            gross_exit = (
                series.open[ends]
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
        "episodes_matched": len(spans),
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
    momentum_only: dict[str, Any],
    premium_only: dict[str, Any],
    random_null: dict[str, float | int],
) -> dict[str, Any]:
    checks = [
        ("15 bps return > 0", main["return"] > 0),
        ("15 bps Sharpe >= 0.50", main["sharpe"] >= 0.50),
        ("MaxDD <= 20%", main["max_drawdown"] <= 0.20),
        ("at least 12 closed trades", main["trades"] >= 12),
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
            "joint state beats momentum-only Sharpe and MaxDD",
            main["sharpe"] > momentum_only["sharpe"]
            and main["max_drawdown"] < momentum_only["max_drawdown"],
        ),
        (
            "joint state beats premium-only Sharpe",
            main["sharpe"] > premium_only["sharpe"],
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
        "# DOGE 永续溢价趋势确认发现结果 (2021-2023)",
        "",
        "> spot 与 swap 查询均硬截止 2024-01-01; 未读取后续年度。",
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
        "history120",
        "history270",
        "entry05",
        "entry15",
        "momentum_only",
        "premium_only",
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
        f"- {'PASS' if row['passed'] else 'FAIL'} - {row['name']}"
        for row in payload["gate"]["checks"]
    )
    lines += [
        "",
        "## Provenance",
        "",
        f"- Spot 1h fingerprint: `{payload['fingerprints']['spot_1h']}`",
        f"- Swap 1h fingerprint: `{payload['fingerprints']['swap_1h']}`",
        f"- Spot 4h fingerprint: `{payload['fingerprints']['spot_4h']}`",
        f"- Swap 4h fingerprint: `{payload['fingerprints']['swap_4h']}`",
        f"- 4h bars: {payload['bars']}",
        f"- Range: `{payload['range']}`",
        "- Costs: 10 bps fee + 5 bps slippage per side; 25 bps stress",
        "- Execution: closed 4h decision, next open fill, 25% spot target",
        "- Protocol: `PERPETUAL_PREMIUM_CONFIRMATION_PROTOCOL_2026-07-22.md`",
        "",
    ]
    if not payload["gate"]["passed"]:
        lines += [
            "按冻结规则, PPC v1 在 discovery 永久停止; 不读取 2024, 不挑邻域替补。",
            "",
        ]
    return "\n".join(lines)


def main() -> int:
    end_ms = to_ms(DISCOVERY_END)
    with Store(DB_PATH) as store:
        spot_1h = load_series(store, INSTRUMENT, "1h", end_ms=end_ms)
        swap_1h = load_series(store, SWAP_INSTRUMENT, "1h", end_ms=end_ms)
        series = load_series(store, INSTRUMENT, TIMEFRAME, end_ms=end_ms)
        swap = load_series(store, SWAP_INSTRUMENT, TIMEFRAME, end_ms=end_ms)
    markets = {
        "spot_1h": spot_1h,
        "swap_1h": swap_1h,
        "spot_4h": series,
        "swap_4h": swap,
    }
    if any(len(market) == 0 for market in markets.values()):
        raise SystemExit("PPC discovery market data missing")
    if any(int(market.ts[-1]) >= end_ms for market in markets.values()):
        raise RuntimeError("PPC discovery query crossed the frozen 2024 boundary")
    if not np.array_equal(spot_1h.ts, swap_1h.ts):
        raise RuntimeError("PPC source 1h spot/swap panel is not exactly aligned")
    if not np.array_equal(series.ts, swap.ts):
        raise RuntimeError("PPC 4h spot/swap panel is not exactly aligned")

    factories = candidate_factories()
    results = {
        name: _run(factory(), series, swap)
        for name, factory in factories.items()
    }
    summaries = {name: _summary(result) for name, result in results.items()}
    main_result = results["main"]
    main = summaries["main"]
    stress = _summary(
        _run(
            factories["main"](),
            series,
            swap,
            slippage_bps=STRESS_SLIPPAGE_BPS,
        )
    )
    yearly = [
        _cold_year(series, swap, factories["main"], year)
        for year in range(2021, 2024)
    ]
    episodes = episode_returns(
        main_result.timestamps,
        main_result.equity,
        main_result.fills,
        main_result.initial_cash,
    )
    observed = float(np.prod(1.0 + np.asarray(episodes, dtype=float)) - 1.0)
    random_null = _matched_random_null(
        series, position_spans(main_result.fills), observed
    )
    neighbors = {
        name: summaries[name]
        for name in ("history120", "history270", "entry05", "entry15")
    }
    gate = _gate(
        main,
        stress,
        yearly,
        neighbors,
        summaries["momentum_only"],
        summaries["premium_only"],
        random_null,
    )
    payload: dict[str, Any] = {
        "study": "doge-perpetual-premium-confirmation-v1",
        "stage": "discovery",
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "query_end_exclusive": DISCOVERY_END,
        "params": asdict(PpcParams()),
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
