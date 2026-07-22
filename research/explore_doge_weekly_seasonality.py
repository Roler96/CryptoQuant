#!/usr/bin/env python
"""Pre-2024 discovery of the DOGE weekly-seasonality (DWS v1) family.

The immutable, result-blind mechanism, family members and gate are documented
in ``WEEKLY_SEASONALITY_PROTOCOL_2026-07-22.md``.  This process queries only
data before 2024-01-01; it cannot expose a later bar to either the strategies
or the reporting code.

The mechanism is orthogonal to every prior DOGE spot study: it reads no price
state, momentum, volatility, volume, cross-asset or derivative input.  The only
signal is the UTC weekday of the bar being decided for.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from cq.context import Context, Series, series_fingerprint
from cq.core.types import CostModel, Intent, MarketSpec, Sizing
from cq.data.feed import load_series
from cq.data.store import Store
from cq.engine.loop import RunResult, run_backtest
from cq.research.metrics import episode_returns, position_spans
from cq.research.split import from_ms, to_ms
from cq.research.stats import sidak_correction
from research.explore_doge_directional_regimes import (
    BASE_FEE_BPS,
    BASE_SLIPPAGE_BPS,
    DB_PATH,
    INITIAL_CASH,
    INSTRUMENT,
    SEED,
    STRESS_SLIPPAGE_BPS,
    ResearchStrategy,
    _cold_year,
    _pct,
    _run,
    _summary,
)

TIMEFRAME = "1d"
DISCOVERY_END = "2024-01-01"
SAMPLES = 10_000
# 40 prior formulas in the DOGE spot attempts ledger plus this study's four
# tradeable candidates (weekdays, ex_mon, ex_sun_only, weekend_only).
REGISTERED_FAMILY_ATTEMPTS = 44
WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
OUTPUT_JSON = Path("reports/research/doge_weekly_seasonality_discovery.json")
OUTPUT_MD = Path(
    "docs/research/doge-spot/WEEKLY_SEASONALITY_DISCOVERY_RESULTS_2026-07-22.md"
)


@dataclass(frozen=True)
class WeeklySeasonalityParams:
    held_days: tuple[int, ...] = (0, 1, 2, 3, 4)
    size: float = 1.0

    def __post_init__(self) -> None:
        if not self.held_days:
            raise ValueError("held_days must not be empty")
        if any(day not in range(7) for day in self.held_days):
            raise ValueError("held_days must be UTC weekday indices in 0..6")
        if tuple(sorted(set(self.held_days))) != self.held_days:
            raise ValueError("held_days must be sorted and unique")
        if not 0 < self.size <= 1:
            raise ValueError("spot size must be in (0, 1]")


class DogeWeeklySeasonality:
    """Hold DOGE only on pre-registered UTC weekdays; cash otherwise.

    Fully causal and stateless: the target for the next bar depends only on
    that bar's calendar weekday, which is known the instant the current bar
    closes and involves no price data at all.
    """

    def __init__(self, params: WeeklySeasonalityParams | None = None):
        self.params = params or WeeklySeasonalityParams()
        self._held = frozenset(self.params.held_days)

    @property
    def name(self) -> str:
        days = "".join(str(day) for day in self.params.held_days)
        return f"doge-wsz-{days}-size{self.params.size:g}"

    @property
    def warmup_bars(self) -> int:
        return 1

    def reset(self) -> None:
        # Stateless: nothing to clear. Present so the engine's reset hook and
        # the WindowedStrategy wrapper find the method they expect.
        return None

    def snapshot_state(self) -> dict[str, object]:
        return {"held_days": list(self.params.held_days), "params": asdict(self.params)}

    def on_bar(self, ctx: Context) -> Intent:
        # decision_time is this bar's close, which is exactly the next bar's
        # open. The next bar is held iff its own weekday is in the set.
        weekday = dt.datetime.fromtimestamp(
            ctx.decision_time / 1000, dt.UTC
        ).weekday()
        target = self.params.size if weekday in self._held else 0.0
        return Intent(target=target, reason=self.name)


def candidate_factories() -> dict[str, Callable[[], ResearchStrategy]]:
    return {
        "weekdays": DogeWeeklySeasonality,
        "ex_mon": lambda: DogeWeeklySeasonality(
            WeeklySeasonalityParams(held_days=(1, 2, 3, 4))
        ),
        "ex_sun_only": lambda: DogeWeeklySeasonality(
            WeeklySeasonalityParams(held_days=(0, 1, 2, 3, 4, 5))
        ),
        "weekend_only": lambda: DogeWeeklySeasonality(
            WeeklySeasonalityParams(held_days=(5, 6))
        ),
        "buy_and_hold": lambda: DogeWeeklySeasonality(
            WeeklySeasonalityParams(held_days=(0, 1, 2, 3, 4, 5, 6))
        ),
    }


def _run_zero_cost(strategy: ResearchStrategy, series: Series) -> RunResult:
    """A frictionless view: separates 'no effect' from 'effect eaten by cost'."""
    return run_backtest(
        strategy,
        series,
        MarketSpec(INSTRUMENT, "spot"),
        INITIAL_CASH,
        costs=CostModel(fee_bps=0.0, slippage_bps=0.0),
        sizing=Sizing.ON_ENTRY,
    )


def _matched_random_null(
    series: Series,
    spans: list[tuple[int, int | None]],
    observed: float,
    costs: CostModel,
    size: float = 1.0,
    samples: int = SAMPLES,
    seed: int = SEED,
    family_trials: int = REGISTERED_FAMILY_ATTEMPTS,
) -> dict[str, float | int]:
    """Random entries matched on entry year, holding bars and round-trip costs.

    Tests whether calendar-anchored holds beat same-year, same-duration holds
    started on random days — i.e. whether the weekday clock carries information
    beyond the fraction of time spent in the market.
    """
    if not spans:
        raise ValueError("matched-random null needs at least one held episode")
    index_of = {int(ts): index for index, ts in enumerate(series.ts)}
    years = np.array([int(from_ms(int(ts))[:4]) for ts in series.ts], dtype=int)
    indexes = np.arange(len(series), dtype=int)
    fee = costs.fee_bps / 10_000
    slip = costs.slippage_bps / 10_000
    cost_factor = ((1 - slip) * (1 - fee)) / ((1 + slip) * (1 + fee))
    rng = np.random.default_rng(seed)
    totals = np.ones(samples, dtype=float)

    for entry_ts, exit_ts in spans:
        entry_index = index_of[int(entry_ts)]
        exit_index = len(series) - 1 if exit_ts is None else index_of[int(exit_ts)]
        holding_bars = exit_index - entry_index
        if holding_bars < 1:
            raise ValueError("every matched episode must hold at least one bar")
        valid_end = indexes + holding_bars < len(series)
        valid_volume = np.zeros(len(series), dtype=bool)
        with_end = indexes[valid_end]
        valid_volume[with_end] = (series.volume[with_end] > 0) & (
            series.volume[with_end + holding_bars] > 0
        )
        candidates = indexes[
            (years == years[entry_index]) & valid_end & valid_volume
        ]
        if len(candidates) == 0:
            raise ValueError(
                f"no random candidates for {entry_ts=} and {holding_bars=}"
            )
        starts = rng.choice(candidates, size=samples, replace=True)
        exits = starts + holding_bars
        gross = series.open[exits] / series.open[starts] * cost_factor
        totals *= 1.0 + size * (gross - 1.0)

    null_returns = totals - 1.0
    exceedances = int(np.sum(null_returns >= observed))
    p_value = (exceedances + 1) / (samples + 1)
    return {
        "samples": samples,
        "episodes": len(spans),
        "observed": observed,
        "null_p05": float(np.percentile(null_returns, 5)),
        "null_median": float(np.median(null_returns)),
        "null_p95": float(np.percentile(null_returns, 95)),
        "p_value": p_value,
        "family_adjusted_p": sidak_correction(p_value, family_trials),
    }


def _block_bootstrap(
    returns: list[float] | np.ndarray, block_size: int, seed: int
) -> dict[str, float | int]:
    """Circular moving-block bootstrap preserving local episode order."""
    values = np.asarray(returns, dtype=float)
    if len(values) == 0:
        return {"block_size": block_size, "p05": 0.0, "median": 0.0, "p95": 0.0}
    blocks = math.ceil(len(values) / block_size)
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, len(values), size=(SAMPLES, blocks))
    offsets = np.arange(block_size)
    idx = ((starts[:, :, None] + offsets) % len(values)).reshape(SAMPLES, -1)
    totals = np.prod(1.0 + values[idx[:, : len(values)]], axis=1) - 1.0
    return {
        "block_size": block_size,
        "p05": float(np.percentile(totals, 5)),
        "median": float(np.median(totals)),
        "p95": float(np.percentile(totals, 95)),
    }


def _year_jackknife(
    returns: list[float] | np.ndarray, entry_years: list[int]
) -> list[dict[str, float | int]]:
    values = np.asarray(returns, dtype=float)
    years = np.asarray(entry_years, dtype=int)
    output: list[dict[str, float | int]] = []
    for year in sorted(set(years.tolist())):
        keep = years != year
        output.append(
            {
                "removed_year": int(year),
                "remaining": int(np.sum(keep)),
                "return": float(np.prod(1.0 + values[keep]) - 1.0),
            }
        )
    return output


def _weekday_profile(series: Series) -> list[dict[str, str | float | int]]:
    """Mean and std of 1d log returns by the UTC weekday they occurred in."""
    log_returns = np.diff(np.log(series.close))
    weekdays = np.array(
        [
            dt.datetime.fromtimestamp(int(ts) / 1000, dt.UTC).weekday()
            for ts in series.ts[1:]
        ],
        dtype=int,
    )
    profile: list[dict[str, str | float | int]] = []
    for day in range(7):
        chunk = log_returns[weekdays == day]
        profile.append(
            {
                "weekday": WEEKDAY_NAMES[day],
                "count": len(chunk),
                "mean": float(np.mean(chunk)) if len(chunk) else 0.0,
                "std": float(np.std(chunk, ddof=1)) if len(chunk) > 1 else 0.0,
            }
        )
    return profile


def _hour_profile(hourly: Series) -> list[dict[str, float | int]]:
    """Mean of 1h log returns by the UTC hour they occurred in."""
    log_returns = np.diff(np.log(hourly.close))
    hours = np.array(
        [
            dt.datetime.fromtimestamp(int(ts) / 1000, dt.UTC).hour
            for ts in hourly.ts[1:]
        ],
        dtype=int,
    )
    profile: list[dict[str, float | int]] = []
    for hour in range(24):
        chunk = log_returns[hours == hour]
        profile.append(
            {
                "hour": hour,
                "count": len(chunk),
                "mean": float(np.mean(chunk)) if len(chunk) else 0.0,
            }
        )
    return profile


def _gate(
    main: dict[str, Any],
    stress: dict[str, Any],
    yearly: list[dict[str, Any]],
    buy_and_hold: dict[str, Any],
    weekend_only: dict[str, Any],
    random_null: dict[str, float | int],
) -> dict[str, Any]:
    checks = [
        ("15 bps return > 0", main["return"] > 0),
        ("15 bps Sharpe >= 0.40", main["sharpe"] >= 0.40),
        ("25 bps/side return > 0", stress["return"] > 0),
        (
            "at least two positive cold-start years",
            sum(row["return"] > 0 for row in yearly) >= 2,
        ),
        ("Sharpe beats buy-and-hold", main["sharpe"] > buy_and_hold["sharpe"]),
        (
            "return and Sharpe beat the weekend-only placebo",
            main["return"] > weekend_only["return"]
            and main["sharpe"] > weekend_only["sharpe"],
        ),
        (
            "matched-random one-sided p < 0.10",
            float(random_null["p_value"]) < 0.10,
        ),
        ("at least fifty held episodes", main["episode_count"] >= 50),
    ]
    passed = all(bool(value) for _, value in checks)
    return {
        "passed": passed,
        "verdict": "DISCOVERY PASS" if passed else "DISCOVERY FAIL",
        "checks": [
            {"name": name, "passed": bool(value)} for name, value in checks
        ],
    }


def _render(payload: dict[str, Any]) -> str:
    main = payload["main"]
    stress = payload["stress_25bps"]
    cand = payload["all_candidates"]
    null = payload["matched_random"]
    lines = [
        "# DOGE 周内季节性发现结果 (2021-2023)",
        "",
        "> 查询在数据库层硬截止 2024-01-01; 2024/2025/2026 未读取。机制只依赖 UTC",
        "> 星期几时钟, 不读取任何价格/动量/波动率/成交量/跨币/衍生品信息。",
        "",
        f"**{payload['gate']['verdict']}**",
        "",
        "## 候选对照 (size=1.0, 15 bps/边)",
        "",
        "| Candidate | Return | Sharpe | MaxDD | Trades | Less best 1 | Episodes |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name in ("weekdays", "ex_mon", "ex_sun_only", "weekend_only", "buy_and_hold"):
        row = cand[name]
        lines.append(
            f"| {name} | {_pct(row['return'])} | {row['sharpe']:.2f} | "
            f"{_pct(-row['max_drawdown'])} | {row['trades']} | "
            f"{_pct(row['return_less_best_1'])} | {row['episode_count']} |"
        )

    lines += [
        "",
        "## 主策略冷启动自然年",
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
        "## 成本敏感度 (主策略)",
        "",
        "| Cost/side | Return | Sharpe |",
        "|---|---:|---:|",
        f"| gross (0 bps) | {_pct(payload['gross']['return'])} | "
        f"{payload['gross']['sharpe']:.2f} |",
        f"| 15 bps | {_pct(main['return'])} | {main['sharpe']:.2f} |",
        f"| 25 bps | {_pct(stress['return'])} | {stress['sharpe']:.2f} |",
        "",
        "## 匹配随机入场 (主策略, trials=44)",
        "",
        f"- Observed: `{_pct(float(null['observed']))}`",
        f"- Null median: `{_pct(float(null['null_median']))}`",
        f"- Null P5-P95: `{_pct(float(null['null_p05']))}` .. "
        f"`{_pct(float(null['null_p95']))}`",
        f"- Raw 单侧 p: `{float(null['p_value']):.6f}`",
        f"- Sidak-adjusted p: `{float(null['family_adjusted_p']):.6f}`",
        "",
        "## Pooled block bootstrap (主策略)",
        "",
        "| Block episodes | P5 | Median | P95 |",
        "|---:|---:|---:|---:|",
    ]
    for row in payload["block_bootstrap"]:
        lines.append(
            f"| {row['block_size']} | {_pct(float(row['p05']))} | "
            f"{_pct(float(row['median']))} | {_pct(float(row['p95']))} |"
        )

    lines += [
        "",
        "## 逐年 jackknife (主策略)",
        "",
        "| Removed year | Remaining episodes | Return |",
        "|---:|---:|---:|",
    ]
    for row in payload["year_jackknife"]:
        lines.append(
            f"| {row['removed_year']} | {row['remaining']} | "
            f"{_pct(float(row['return']))} |"
        )

    lines += [
        "",
        "## 描述性季节性图 (仅解释, 不用于选择)",
        "",
        "### UTC 星期几 1d 对数收益",
        "",
        "| Weekday | Count | Mean | Std |",
        "|---|---:|---:|---:|",
    ]
    for row in payload["weekday_profile"]:
        lines.append(
            f"| {row['weekday']} | {row['count']} | "
            f"{float(row['mean']) * 100:+.3f}% | {float(row['std']) * 100:.3f}% |"
        )

    lines += [
        "",
        "### UTC 小时 1h 对数收益均值",
        "",
        "| Hour | Count | Mean |",
        "|---:|---:|---:|",
    ]
    for row in payload["hour_profile"]:
        lines.append(
            f"| {row['hour']:02d} | {row['count']} | {float(row['mean']) * 100:+.4f}% |"
        )

    lines += ["", "## 发现门明细", ""]
    lines.extend(
        f"- {'PASS' if check['passed'] else 'FAIL'} - {check['name']}"
        for check in payload["gate"]["checks"]
    )
    lines += [
        "",
        "## Provenance",
        "",
        f"- Source fingerprint (1h): `{payload['source_fingerprint']}`",
        f"- Aggregated fingerprint (1d): `{payload['data_fingerprint']}`",
        f"- Bars (1d): {payload['bars']}",
        f"- Range: `{payload['range']}`",
        "- Query hard end: `2024-01-01 00:00 UTC` (exclusive)",
        "- Costs: 10 bps fee + 5 bps slippage per side; 25 bps stress",
        "- Execution: closed 1d decision, next 1d open fill, ON_ENTRY, long/cash",
        f"- Registered attempts (cumulative): {payload['registered_family_attempts']}",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    end_ms = to_ms(DISCOVERY_END)
    with Store(DB_PATH) as store:
        hourly = load_series(store, INSTRUMENT, "1h", end_ms=end_ms)
        series = load_series(store, INSTRUMENT, TIMEFRAME, end_ms=end_ms)
    if len(series) == 0 or len(hourly) == 0:
        raise SystemExit("DOGE-USDT discovery data missing")
    if int(series.ts[-1]) >= end_ms or int(hourly.ts[-1]) >= end_ms:
        raise RuntimeError("weekly-seasonality discovery crossed the 2024 boundary")

    factories = candidate_factories()
    summaries = {
        name: _summary(_run(factory(), series, slippage_bps=BASE_SLIPPAGE_BPS))
        for name, factory in factories.items()
    }
    main_summary = summaries["weekdays"]
    stress = _summary(
        _run(factories["weekdays"](), series, slippage_bps=STRESS_SLIPPAGE_BPS)
    )
    gross = _summary(_run_zero_cost(factories["weekdays"](), series))
    yearly = [
        _cold_year(series, factories["weekdays"], year) for year in range(2021, 2024)
    ]

    main_result = _run(factories["weekdays"](), series, slippage_bps=BASE_SLIPPAGE_BPS)
    spans = position_spans(main_result.fills)
    episodes = episode_returns(
        main_result.timestamps,
        main_result.equity,
        main_result.fills,
        main_result.initial_cash,
    )
    if len(spans) != len(episodes):
        raise RuntimeError("episode spans and returns disagree")
    observed = float(np.prod(1.0 + np.asarray(episodes, dtype=float)) - 1.0)
    entry_years = [int(from_ms(int(entry_ts))[:4]) for entry_ts, _ in spans]
    random_null = _matched_random_null(
        series,
        spans,
        observed,
        costs=CostModel(fee_bps=BASE_FEE_BPS, slippage_bps=BASE_SLIPPAGE_BPS),
    )
    blocks = [_block_bootstrap(episodes, size, SEED + size) for size in (2, 4)]
    jackknife = _year_jackknife(episodes, entry_years)

    gate = _gate(
        main_summary,
        stress,
        yearly,
        summaries["buy_and_hold"],
        summaries["weekend_only"],
        random_null,
    )

    payload: dict[str, Any] = {
        "study": "doge-weekly-seasonality-v1",
        "stage": "discovery",
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "query_end_exclusive": DISCOVERY_END,
        "registered_family_attempts": REGISTERED_FAMILY_ATTEMPTS,
        "source_fingerprint": series_fingerprint(hourly),
        "data_fingerprint": series_fingerprint(series),
        "bars": len(series),
        "range": f"{from_ms(int(series.ts[0]))}..{from_ms(int(series.ts[-1]))}",
        "main": main_summary,
        "stress_25bps": stress,
        "gross": gross,
        "yearly": yearly,
        "all_candidates": summaries,
        "matched_random": random_null,
        "block_bootstrap": blocks,
        "year_jackknife": jackknife,
        "weekday_profile": _weekday_profile(series),
        "hour_profile": _hour_profile(hourly),
        "gate": gate,
    }
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    OUTPUT_MD.write_text(_render(payload), encoding="utf-8")
    print(_render(payload))
    print(f"JSON: {OUTPUT_JSON}")
    print(f"REPORT: {OUTPUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
