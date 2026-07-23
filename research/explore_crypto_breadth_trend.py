#!/usr/bin/env python
"""Discovery for the frozen crypto-breadth-confirmed BTC trend hypothesis.

The candidate family and every gate are fixed in
``CRYPTO_BREADTH_TREND_PROTOCOL_2026-07-23.md``.  All three database queries
end exclusively at 2025-06-01; this process must not expose validation bars.
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
INSTRUMENT = "BTC-USDT"
ETH_INSTRUMENT = "ETH-USDT"
DOGE_INSTRUMENT = "DOGE-USDT"
TIMEFRAME = "1d"
DISCOVERY_START = "2021-01-01"
DISCOVERY_END = "2025-06-01"
INITIAL_CASH = 10_000.0
BASE_FEE_BPS = 10.0
BASE_SLIPPAGE_BPS = 5.0
STRESS_SLIPPAGE_BPS = 15.0
SAMPLES = 10_000
SEED = 20260723
FAMILY_TRIALS = 5
OUTPUT_JSON = Path("reports/research/crypto_breadth_trend_discovery.json")
OUTPUT_MD = Path(
    "docs/research/crypto-spot/CRYPTO_BREADTH_TREND_DISCOVERY_RESULTS_2026-07-23.md"
)


class ResearchStrategy(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def warmup_bars(self) -> int: ...

    def reset(self) -> None: ...

    def on_bar(self, ctx: Context) -> Intent: ...


@dataclass(frozen=True)
class CbtParams:
    """Frozen CBT parameters."""

    momentum_days: int = 63
    trend_days: int = 200
    min_breadth: int = 2
    size: float = 1.0
    use_breadth: bool = True
    use_trend: bool = True

    def __post_init__(self) -> None:
        if self.momentum_days < 2:
            raise ValueError("momentum_days must be at least two")
        if self.trend_days < 2:
            raise ValueError("trend_days must be at least two")
        if self.min_breadth not in (1, 2, 3):
            raise ValueError("min_breadth must be one of 1, 2, 3")
        if not 0 < self.size <= 1:
            raise ValueError("spot size must be in (0, 1]")
        if not self.use_breadth and not self.use_trend:
            raise ValueError("CBT must keep at least one of breadth or trend")


class CryptoBreadthTrend:
    """Hold BTC only when its trend is confirmed by cross-asset breadth."""

    def __init__(self, params: CbtParams | None = None):
        self.params = params or CbtParams()
        self._target = 0.0

    @property
    def name(self) -> str:
        p = self.params
        components = []
        if p.use_breadth:
            components.append(f"breadth{p.min_breadth}-m{p.momentum_days}")
        if p.use_trend:
            components.append(f"sma{p.trend_days}")
        return f"crypto-cbt-{'-'.join(components)}"

    @property
    def warmup_bars(self) -> int:
        p = self.params
        breadth_warmup = p.momentum_days + 1 if p.use_breadth else 1
        trend_warmup = p.trend_days if p.use_trend else 1
        return max(breadth_warmup, trend_warmup)

    def reset(self) -> None:
        self._target = 0.0

    def snapshot_state(self) -> dict[str, object]:
        return {"target": self._target, "params": asdict(self.params)}

    def restore_state(self, state: dict[str, object]) -> None:
        if state.get("params") != asdict(self.params):
            raise ValueError("CBT checkpoint configuration does not match")
        raw_target = state.get("target")
        if (
            isinstance(raw_target, bool)
            or not isinstance(raw_target, (int, float))
            or float(raw_target) not in (0.0, self.params.size)
        ):
            raise ValueError("invalid CBT checkpoint target")
        self._target = float(raw_target)

    def on_bar(self, ctx: Context) -> Intent:
        p = self.params
        breadth_ok = True
        if p.use_breadth:
            eth = ctx.market(ETH_INSTRUMENT, TIMEFRAME)
            doge = ctx.market(DOGE_INSTRUMENT, TIMEFRAME)
            if not eth.available or not doge.available:
                self._target = 0.0
                return Intent(target=0.0, reason=f"{self.name}-aux-unavailable")
            if eth.bar.ts != ctx.now or doge.bar.ts != ctx.now:
                self._target = 0.0
                return Intent(target=0.0, reason=f"{self.name}-aux-unaligned")

            horizon = p.momentum_days + 1
            paths = (ctx.close(horizon), eth.close(horizon), doge.close(horizon))
            positive = sum(float(path[-1]) > float(path[0]) for path in paths)
            breadth_ok = positive >= p.min_breadth

        trend_ok = True
        if p.use_trend:
            close = ctx.close(p.trend_days)
            trend_ok = float(close[-1]) > float(np.mean(close))

        self._target = p.size if breadth_ok and trend_ok else 0.0
        return Intent(target=self._target, reason=self.name)


class BuyAndHold:
    """Causal next-open BTC benchmark."""

    name = "btc-buy-and-hold"
    warmup_bars = 1

    def reset(self) -> None:
        pass

    def on_bar(self, ctx: Context) -> Intent:
        return Intent(target=1.0, reason=self.name)


class WindowedStrategy:
    """Cold-start an inner strategy and stay in cash outside one time span."""

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


def candidate_factories() -> dict[str, Callable[[], CryptoBreadthTrend]]:
    return {
        "main": CryptoBreadthTrend,
        "momentum_fast": lambda: CryptoBreadthTrend(CbtParams(momentum_days=42)),
        "momentum_slow": lambda: CryptoBreadthTrend(CbtParams(momentum_days=84)),
        "trend_fast": lambda: CryptoBreadthTrend(CbtParams(trend_days=150)),
        "trend_slow": lambda: CryptoBreadthTrend(CbtParams(trend_days=250)),
        "btc_trend_only": lambda: CryptoBreadthTrend(
            CbtParams(use_breadth=False)
        ),
        "breadth_only": lambda: CryptoBreadthTrend(CbtParams(use_trend=False)),
    }


def _run(
    strategy: ResearchStrategy,
    btc: Series,
    aux: tuple[Series, Series],
    slippage_bps: float = BASE_SLIPPAGE_BPS,
) -> RunResult:
    return run_backtest(
        strategy,
        btc,
        MarketSpec(INSTRUMENT, "spot"),
        INITIAL_CASH,
        costs=CostModel(fee_bps=BASE_FEE_BPS, slippage_bps=slippage_bps),
        aux=aux,
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
    realised = sorted((trade.net_pnl for trade in trades), reverse=True)
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
            (result.final_equity - (realised[0] if realised else 0.0))
            / result.initial_cash
            - 1.0
        ),
        "episode_count": len(episodes),
        "mean_episode_return": float(np.mean(episodes)) if episodes else 0.0,
        "bootstrap_probability_of_loss": bootstrap.probability_of_loss,
        "bootstrap_p05": bootstrap.percentile_05,
        "fills": len(result.fills),
        "rejections": len(result.rejections),
    }


def _cold_period(
    btc: Series,
    aux: tuple[Series, Series],
    factory: Callable[[], ResearchStrategy],
    label: str,
    start: str,
    end: str,
) -> dict[str, Any]:
    start_ms = to_ms(start)
    end_ms = to_ms(end)
    result = _run(WindowedStrategy(factory, start_ms, end_ms), btc, aux)
    indexes = [
        index
        for index, ts in enumerate(result.timestamps)
        if start_ms <= int(ts) < end_ms
    ]
    if not indexes:
        raise ValueError(f"cold period {label} has no bars")
    timestamps = [result.timestamps[index] for index in indexes]
    equity = [result.equity[index] for index in indexes]
    fills = [fill for fill in result.fills if start_ms <= fill.ts < end_ms]
    opening = result.equity[indexes[0] - 1] if indexes[0] > 0 else INITIAL_CASH
    metrics = compute_metrics(timestamps, equity, fills, opening)
    return {
        "period": label,
        "start": start,
        "end": end,
        "return": equity[-1] / opening - 1.0,
        "sharpe": metrics.sharpe,
        "max_drawdown": metrics.max_drawdown,
        "trades": metrics.trades,
    }


def _matched_random_null(
    series: Series,
    spans: list[tuple[int, int | None]],
    observed: float,
    size: float = 1.0,
    samples: int = SAMPLES,
    seed: int = SEED,
) -> dict[str, float | int]:
    """Random BTC entries matched by entry year, holding days and costs."""
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
    rng = np.random.default_rng(seed)
    totals = np.ones(samples, dtype=float)
    fee = BASE_FEE_BPS / 10_000
    slip = BASE_SLIPPAGE_BPS / 10_000
    gross_entry = (1.0 + slip) * (1.0 + fee)

    for entry_ts, exit_ts in spans:
        entry_index = index_of[int(entry_ts)]
        is_open = exit_ts is None
        exit_index = len(series) - 1 if is_open else index_of[int(exit_ts)]
        holding_bars = exit_index - entry_index
        if holding_bars < 1:
            raise ValueError("CBT episodes must hold at least one daily bar")
        valid_end = indexes + holding_bars < len(series)
        candidates = indexes[(years == years[entry_index]) & valid_end]
        if len(candidates) == 0:
            raise ValueError("no year-matched random BTC entry candidates")
        starts = rng.choice(candidates, size=samples, replace=True)
        exits = starts + holding_bars
        if is_open:
            gross_exit = series.close[exits] / series.open[starts]
        else:
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
    periods: list[dict[str, Any]],
    neighbors: dict[str, dict[str, Any]],
    trend_only: dict[str, Any],
    breadth_only: dict[str, Any],
    buy_hold: dict[str, Any],
    random_null: dict[str, float | int],
) -> dict[str, Any]:
    checks = [
        ("15 bps return > 0", main["return"] > 0),
        ("15 bps Sharpe >= 0.75", main["sharpe"] >= 0.75),
        ("MaxDD <= 35%", main["max_drawdown"] <= 0.35),
        ("at least 8 closed trades", main["trades"] >= 8),
        (
            "at least 3 of 5 cold-start periods positive",
            sum(row["return"] > 0 for row in periods) >= 3,
        ),
        ("25 bps/side return > 0", stress["return"] > 0),
        ("return less best closed trade > 0", main["return_less_best_1"] > 0),
        ("episode bootstrap P5 > 0", main["bootstrap_p05"] > 0),
        (
            "all four fixed neighbors profitable",
            all(row["return"] > 0 for row in neighbors.values()),
        ),
        (
            "MaxDD at least 25% below BTC buy-and-hold",
            main["max_drawdown"] <= 0.75 * buy_hold["max_drawdown"],
        ),
        (
            "breadth improves trend-only Sharpe without higher MaxDD",
            main["sharpe"] > trend_only["sharpe"]
            and main["max_drawdown"] <= trend_only["max_drawdown"],
        ),
        (
            "trend filter improves breadth-only Sharpe",
            main["sharpe"] > breadth_only["sharpe"],
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
        "# 加密市场广度确认 BTC 趋势发现结果 (CBT v1)",
        "",
        "> 三市场查询均在数据库层排他硬截止 2025-06-01; 未读取验证窗。",
        "",
        "## 结论",
        "",
        f"**{payload['gate']['verdict']}**",
        "",
        "## 冻结主版本 (63d breadth + BTC SMA200, 15bps/边)",
        "",
        "| Return | Sharpe | MaxDD | Trades | Mean episode | Less best 1 | 25bps | Bootstrap P5 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"| {_pct(main['return'])} | {main['sharpe']:.2f} | "
        f"{_pct(-main['max_drawdown'])} | {main['trades']} | "
        f"{_pct(main['mean_episode_return'])} | {_pct(main['return_less_best_1'])} | "
        f"{_pct(stress['return'])} | {_pct(main['bootstrap_p05'])} |",
        "",
        "## 冷启动时段",
        "",
        "| Period | Return | Sharpe | MaxDD | Trades |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in payload["cold_periods"]:
        lines.append(
            f"| {row['period']} | {_pct(row['return'])} | {row['sharpe']:.2f} | "
            f"{_pct(-row['max_drawdown'])} | {row['trades']} |"
        )
    lines += [
        "",
        "## 冻结邻域、消融与基准 (15bps/边)",
        "",
        "| Version | Return | Sharpe | MaxDD | Trades |",
        "|---|---:|---:|---:|---:|",
    ]
    for name in (
        "momentum_fast",
        "momentum_slow",
        "trend_fast",
        "trend_slow",
        "btc_trend_only",
        "breadth_only",
        "buy_and_hold",
    ):
        row = payload["variants"][name]
        lines.append(
            f"| {name} | {_pct(row['return'])} | {row['sharpe']:.2f} | "
            f"{_pct(-row['max_drawdown'])} | {row['trades']} |"
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
        f"- Split fingerprint: `{payload['split_fingerprint']}`",
        f"- BTC 1h / 1d: `{payload['fingerprints']['BTC-USDT']['1h']}` / "
        f"`{payload['fingerprints']['BTC-USDT']['1d']}`",
        f"- ETH 1h / 1d: `{payload['fingerprints']['ETH-USDT']['1h']}` / "
        f"`{payload['fingerprints']['ETH-USDT']['1d']}`",
        f"- DOGE 1h / 1d: `{payload['fingerprints']['DOGE-USDT']['1h']}` / "
        f"`{payload['fingerprints']['DOGE-USDT']['1d']}`",
        f"- Daily bars: {payload['bars']}",
        f"- Range: `{payload['range']}`",
        "- Query hard end: `2025-06-01 00:00 UTC` (exclusive)",
        "- Costs: 10 bps fee + 5 bps slippage per side; 25 bps stress",
        "- Execution: closed UTC daily bar decision, next daily open fill, ON_ENTRY",
        "- Registered tradable attempts: 5",
        "- Protocol: `CRYPTO_BREADTH_TREND_PROTOCOL_2026-07-23.md`",
        "",
    ]
    if not payload["gate"]["passed"]:
        lines += [
            "按冻结规则, CBT v1 在 discovery 永久停止; 不读取验证窗、不从邻域替补、"
            "不修改参数。",
            "",
        ]
    else:
        lines += [
            "CBT v1 只获得打开一次验证窗的资格; 本报告本身不批准真实资金。",
            "",
        ]
    return "\n".join(lines)


def main() -> int:
    start_ms = to_ms(DISCOVERY_START)
    end_ms = to_ms(DISCOVERY_END)
    instruments = (INSTRUMENT, ETH_INSTRUMENT, DOGE_INSTRUMENT)
    hourly: dict[str, Series] = {}
    daily: dict[str, Series] = {}
    with Store(DB_PATH) as store:
        for instrument in instruments:
            hourly[instrument] = load_series(
                store,
                instrument,
                "1h",
                start_ms=start_ms,
                end_ms=end_ms,
            )
            daily[instrument] = load_series(
                store,
                instrument,
                TIMEFRAME,
                start_ms=start_ms,
                end_ms=end_ms,
            )

    for instrument in instruments:
        if len(hourly[instrument]) == 0 or len(daily[instrument]) == 0:
            raise SystemExit(f"{instrument} CBT discovery data missing")
        if (
            int(hourly[instrument].ts[-1]) >= end_ms
            or int(daily[instrument].ts[-1]) >= end_ms
        ):
            raise RuntimeError(f"{instrument} query crossed the validation boundary")

    btc = daily[INSTRUMENT]
    aux = (daily[ETH_INSTRUMENT], daily[DOGE_INSTRUMENT])
    if any(not np.array_equal(btc.ts, series.ts) for series in aux):
        raise RuntimeError("CBT daily markets are not exactly aligned")

    factories = candidate_factories()
    results = {
        name: _run(factory(), btc, aux)
        for name, factory in factories.items()
    }
    summaries = {name: _summary(result) for name, result in results.items()}
    main_result = results["main"]
    main = summaries["main"]
    stress = _summary(
        _run(
            factories["main"](),
            btc,
            aux,
            slippage_bps=STRESS_SLIPPAGE_BPS,
        )
    )
    cold_specs = [
        ("2021", "2021-01-01", "2022-01-01"),
        ("2022", "2022-01-01", "2023-01-01"),
        ("2023", "2023-01-01", "2024-01-01"),
        ("2024", "2024-01-01", "2025-01-01"),
        ("2025 YTD", "2025-01-01", DISCOVERY_END),
    ]
    cold_periods = [
        _cold_period(btc, aux, factories["main"], label, start, end)
        for label, start, end in cold_specs
    ]
    buy_hold = _summary(_run(BuyAndHold(), btc, aux))
    spans = position_spans(main_result.fills)
    episodes = episode_returns(
        main_result.timestamps,
        main_result.equity,
        main_result.fills,
        main_result.initial_cash,
    )
    observed = float(np.prod(1.0 + np.asarray(episodes, dtype=float)) - 1.0)
    random_null = _matched_random_null(btc, spans, observed)
    neighbor_names = ("momentum_fast", "momentum_slow", "trend_fast", "trend_slow")
    neighbors = {name: summaries[name] for name in neighbor_names}
    gate = _gate(
        main,
        stress,
        cold_periods,
        neighbors,
        summaries["btc_trend_only"],
        summaries["breadth_only"],
        buy_hold,
        random_null,
    )

    from cq.research.split import Segment, SplitPlan

    split = SplitPlan(
        study="crypto-breadth-trend-v1",
        segments=(
            Segment(
                "discovery",
                DISCOVERY_START,
                DISCOVERY_END,
                role="explore",
            ),
        ),
    )
    payload: dict[str, Any] = {
        "study": "crypto-breadth-trend-v1",
        "stage": "discovery",
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "query_start_inclusive": DISCOVERY_START,
        "query_end_exclusive": DISCOVERY_END,
        "split_fingerprint": split.fingerprint,
        "params": asdict(CbtParams()),
        "family_trials": FAMILY_TRIALS,
        "fingerprints": {
            instrument: {
                "1h": series_fingerprint(hourly[instrument]),
                "1d": series_fingerprint(daily[instrument]),
            }
            for instrument in instruments
        },
        "bars": len(btc),
        "range": f"{from_ms(int(btc.ts[0]))}..{from_ms(int(btc.ts[-1]))}",
        "main": main,
        "stress_25bps": stress,
        "cold_periods": cold_periods,
        "variants": {
            **summaries,
            "buy_and_hold": buy_hold,
        },
        "matched_random_null": random_null,
        "gate": gate,
        "holdout_accessed": False,
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
