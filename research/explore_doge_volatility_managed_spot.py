#!/usr/bin/env python
"""Pre-2024 discovery of DOGE volatility-managed spot sizing (VMS v1).

The immutable, result-blind mechanism, family and gate are documented in
``VOLATILITY_MANAGED_SPOT_PROTOCOL_2026-07-22.md``.  This process queries only
data before 2024-01-01.

Unlike the 44 prior DOGE spot formulas, VMS never times entry: it is always
long and only scales the weight by inverse realised volatility (capped at 1.0,
so it is pure spot with no leverage).  The matched-random-entry null that
rejected every timing signal therefore does not apply; the honest question is
whether this sizing rule's risk-adjusted return beats constant full exposure,
tested by the Sharpe difference against buy-and-hold.
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
from numpy.lib.stride_tricks import sliding_window_view

from cq.context import Context, Series, series_fingerprint
from cq.core.types import CostModel, Intent, MarketSpec, Sizing
from cq.data.feed import load_series
from cq.data.store import Store
from cq.engine.loop import RunResult, run_backtest
from cq.research.metrics import (
    bars_per_year,
    max_drawdown,
    per_bar_returns,
    sharpe_ratio,
)
from cq.research.split import from_ms, to_ms
from cq.research.stats import deflated_sharpe_ratio, sidak_correction
from research.explore_doge_directional_regimes import (
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
BLOCK_SIZE = 20
# 44 prior formulas plus this study's five variants (vms, rv10, rv40, med365,
# anti). buy_and_hold is a benchmark, not a candidate.
REGISTERED_FAMILY_ATTEMPTS = 49
OUTPUT_JSON = Path("reports/research/doge_volatility_managed_spot_discovery.json")
OUTPUT_MD = Path(
    "docs/research/doge-spot/VOLATILITY_MANAGED_SPOT_DISCOVERY_RESULTS_2026-07-22.md"
)


@dataclass(frozen=True)
class VmsParams:
    rv_window: int = 20
    median_window: int = 180
    size_cap: float = 1.0
    quantize: float = 0.05
    direction: str = "inverse"

    def __post_init__(self) -> None:
        if self.rv_window < 2:
            raise ValueError("rv_window must be at least two bars")
        if self.median_window < 2:
            raise ValueError("median_window must be at least two bars")
        if not 0 < self.size_cap <= 1:
            raise ValueError("size_cap must be in (0, 1]")
        if not 0 < self.quantize <= self.size_cap:
            raise ValueError("quantize must be in (0, size_cap]")
        if self.direction not in ("inverse", "anti"):
            raise ValueError("direction must be 'inverse' or 'anti'")


class DogeVolatilityManagedSpot:
    """Always long DOGE, weight scaled by inverse realised volatility.

    Causal and stateless. The weight depends only on the trailing realised
    volatility relative to its own recent median, so a rally that arrives with
    high volatility is met with a smaller position — the mechanism's central
    risk, measured rather than assumed away.
    """

    def __init__(self, params: VmsParams | None = None):
        self.params = params or VmsParams()

    @property
    def name(self) -> str:
        p = self.params
        return f"doge-vms-{p.direction}-{p.rv_window}-{p.median_window}d"

    @property
    def warmup_bars(self) -> int:
        return self.params.rv_window + self.params.median_window + 1

    def reset(self) -> None:
        # Stateless: nothing to clear.
        return None

    def snapshot_state(self) -> dict[str, object]:
        return {"params": asdict(self.params)}

    def on_bar(self, ctx: Context) -> Intent:
        p = self.params
        close = ctx.close(self.warmup_bars)
        log_returns = np.diff(np.log(close))
        rv_series = sliding_window_view(log_returns, p.rv_window).std(axis=1, ddof=1)
        current_rv = float(rv_series[-1])
        reference = float(np.median(rv_series[:-1]))

        if current_rv <= 0.0:
            raw = p.size_cap
        elif p.direction == "inverse":
            raw = reference / current_rv
        else:
            raw = current_rv / reference if reference > 0 else 0.0

        weight = float(np.clip(raw, 0.0, p.size_cap))
        weight = round(weight / p.quantize) * p.quantize
        weight = float(np.clip(weight, 0.0, p.size_cap))
        return Intent(target=weight, reason=self.name)


def candidate_factories() -> dict[str, Callable[[], ResearchStrategy]]:
    return {
        "vms": DogeVolatilityManagedSpot,
        "rv10": lambda: DogeVolatilityManagedSpot(VmsParams(rv_window=10)),
        "rv40": lambda: DogeVolatilityManagedSpot(VmsParams(rv_window=40)),
        "med365": lambda: DogeVolatilityManagedSpot(VmsParams(median_window=365)),
        "anti": lambda: DogeVolatilityManagedSpot(VmsParams(direction="anti")),
    }


class _AlwaysFull:
    """The honest buy-and-hold benchmark: constant full weight, no churn."""

    name = "doge-buy-and-hold"
    warmup_bars = 1

    def reset(self) -> None:
        return None

    def on_bar(self, ctx: Context) -> Intent:
        return Intent(target=1.0, reason=self.name)


def _run_zero_cost(strategy: ResearchStrategy, series: Series) -> RunResult:
    """A frictionless view: separates 'no edge' from 'edge eaten by turnover'."""
    return run_backtest(
        strategy,
        series,
        MarketSpec(INSTRUMENT, "spot"),
        INITIAL_CASH,
        costs=CostModel(fee_bps=0.0, slippage_bps=0.0),
        sizing=Sizing.ON_ENTRY,
    )


def _windowed(result: RunResult, i0: int) -> dict[str, Any]:
    """Metrics over equity[i0:], opening from the bar just before i0."""
    if i0 < 1 or i0 >= len(result.equity):
        raise ValueError(f"window start {i0} outside run of {len(result.equity)} bars")
    opening = float(result.equity[i0 - 1])
    equity = np.concatenate([[opening], np.asarray(result.equity[i0:], dtype=float)])
    timestamps = result.timestamps[i0:]
    returns = per_bar_returns(equity)
    per_year = bars_per_year(timestamps)
    return {
        "return": float(equity[-1] / opening - 1.0),
        "sharpe": sharpe_ratio(returns, per_year),
        "max_drawdown": max_drawdown(equity),
        "returns": returns,
        "per_year": per_year,
        "bars": len(returns),
    }


def _weight_path(
    factory: Callable[[], ResearchStrategy], series: Series, i0: int
) -> dict[str, float]:
    """Average exposure and one-way turnover of the intended weight path."""
    strategy = factory()
    ctx = Context(series)
    weights: list[float] = []
    for index in range(i0, len(series)):
        ctx.seek(index)
        weights.append(strategy.on_bar(ctx).target)
    path = np.asarray(weights, dtype=float)
    turnover = float(np.sum(np.abs(np.diff(path)))) if len(path) > 1 else 0.0
    return {
        "avg_exposure": float(np.mean(path)) if len(path) else 0.0,
        "min_exposure": float(np.min(path)) if len(path) else 0.0,
        "one_way_turnover": turnover,
    }


def _joint_block_sharpe_diff(
    vms_returns: np.ndarray,
    bh_returns: np.ndarray,
    per_year: float,
    observed_diff: float,
    seed: int = SEED,
) -> dict[str, float | int]:
    """Bootstrap the VMS-minus-BH Sharpe gap with joint circular blocks."""
    if len(vms_returns) != len(bh_returns):
        raise ValueError("VMS and BH return series must align bar for bar")
    n = len(vms_returns)
    if n < BLOCK_SIZE:
        raise ValueError("not enough aligned bars for the block bootstrap")
    blocks = math.ceil(n / BLOCK_SIZE)
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n, size=(SAMPLES, blocks))
    offsets = np.arange(BLOCK_SIZE)
    idx = ((starts[:, :, None] + offsets) % n).reshape(SAMPLES, -1)[:, :n]

    def _sharpe(sample: np.ndarray) -> np.ndarray:
        mean = sample.mean(axis=1)
        std = sample.std(axis=1, ddof=1)
        return np.where(std > 0, mean / std * math.sqrt(per_year), 0.0)

    diff = _sharpe(vms_returns[idx]) - _sharpe(bh_returns[idx])
    # One-sided: how often chance fails to put VMS above BH.
    p_value = (int(np.sum(diff <= 0.0)) + 1) / (SAMPLES + 1)
    return {
        "block_size": BLOCK_SIZE,
        "observed_sharpe_diff": observed_diff,
        "diff_p05": float(np.percentile(diff, 5)),
        "diff_median": float(np.median(diff)),
        "diff_p95": float(np.percentile(diff, 95)),
        "p_value": p_value,
        "family_adjusted_p": sidak_correction(p_value, REGISTERED_FAMILY_ATTEMPTS),
    }


def _cold_year_pair(
    series: Series,
    vms_factory: Callable[[], ResearchStrategy],
    bh_factory: Callable[[], ResearchStrategy],
    year: int,
) -> dict[str, Any]:
    vms = _cold_year(series, vms_factory, year)
    bh = _cold_year(series, bh_factory, year)
    return {
        "year": year,
        "vms_return": vms["return"],
        "vms_sharpe": vms["sharpe"],
        "vms_max_drawdown": vms["max_drawdown"],
        "bh_return": bh["return"],
        "bh_sharpe": bh["sharpe"],
        "bh_max_drawdown": bh["max_drawdown"],
        "vms_beats_bh_sharpe": vms["sharpe"] > bh["sharpe"],
    }


def _gate(
    vms: dict[str, Any],
    stress_return: float,
    buy_and_hold: dict[str, Any],
    anti: dict[str, Any],
    bootstrap: dict[str, float | int],
    yearly: list[dict[str, Any]],
) -> dict[str, Any]:
    checks = [
        ("15 bps return > 0", vms["return"] > 0),
        ("Sharpe beats buy-and-hold", vms["sharpe"] > buy_and_hold["sharpe"]),
        (
            "MaxDD below buy-and-hold",
            vms["max_drawdown"] < buy_and_hold["max_drawdown"],
        ),
        ("25 bps/side return > 0", stress_return > 0),
        ("Sharpe beats the anti-vol placebo", vms["sharpe"] > anti["sharpe"]),
        (
            "joint block-bootstrap one-sided p < 0.10",
            float(bootstrap["p_value"]) < 0.10,
        ),
        (
            "Sharpe beats buy-and-hold in at least two cold-start years",
            sum(row["vms_beats_bh_sharpe"] for row in yearly) >= 2,
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


def _render(payload: dict[str, Any]) -> str:
    win = payload["windowed"]
    boot = payload["sharpe_bootstrap"]
    lines = [
        "# DOGE 波动率管理现货发现结果 (2021-2023)",
        "",
        "> 查询在数据库层硬截止 2024-01-01。VMS 永远做多、只按逆波动率调整仓位, 因此",
        "> 匹配随机入场零假设不适用; 主检验改为对 buy-and-hold 的 Sharpe 差。",
        f"> 所有对比在共同 post-warmup 窗口 (bar index >= {payload['window_start']}) 上进行。",
        "",
        f"**{payload['gate']['verdict']}**",
        "",
        "## 候选对照 (共同窗口, 15 bps/边)",
        "",
        "| Candidate | Return | Sharpe | MaxDD | Avg exp | Turnover |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name in ("vms", "rv10", "rv40", "med365", "anti", "buy_and_hold"):
        row = win[name]
        exp = payload["exposure"].get(name, {})
        avg = exp.get("avg_exposure")
        turn = exp.get("one_way_turnover")
        avg_s = f"{avg * 100:.0f}%" if avg is not None else "—"
        turn_s = f"{turn:.1f}x" if turn is not None else "—"
        lines.append(
            f"| {name} | {_pct(row['return'])} | {row['sharpe']:.2f} | "
            f"{_pct(-row['max_drawdown'])} | {avg_s} | {turn_s} |"
        )

    lines += [
        "",
        "## 成本敏感度 (主策略, 共同窗口)",
        "",
        "| Cost/side | Return | Sharpe |",
        "|---|---:|---:|",
        f"| gross (0 bps) | {_pct(payload['gross']['return'])} | "
        f"{payload['gross']['sharpe']:.2f} |",
        f"| 15 bps | {_pct(win['vms']['return'])} | {win['vms']['sharpe']:.2f} |",
        f"| 25 bps | {_pct(payload['stress_25bps']['return'])} | "
        f"{payload['stress_25bps']['sharpe']:.2f} |",
        "",
        "## Sharpe 差检验 (VMS - buy_and_hold, 联合 block bootstrap)",
        "",
        f"- Observed Sharpe: VMS `{win['vms']['sharpe']:.3f}` vs BH "
        f"`{win['buy_and_hold']['sharpe']:.3f}` → diff "
        f"`{float(boot['observed_sharpe_diff']):+.3f}`",
        f"- Bootstrap diff P5-P95: `{float(boot['diff_p05']):+.3f}` .. "
        f"`{float(boot['diff_p95']):+.3f}` (median `{float(boot['diff_median']):+.3f}`)",
        f"- 单侧 p(Sharpe_VMS <= Sharpe_BH): `{float(boot['p_value']):.6f}`",
        f"- Sidak-adjusted p (trials=49): "
        f"`{float(boot['family_adjusted_p']):.6f}`",
        f"- VMS deflated Sharpe (per-bar, trials=49): "
        f"`{payload['deflated_sharpe']:.4f}`",
        "",
        "## 逐年冷启动对照 (VMS vs buy_and_hold)",
        "",
        "| Year | VMS Ret | VMS Sharpe | VMS MaxDD | BH Ret | BH Sharpe | BH MaxDD | VMS>BH |",
        "|---:|---:|---:|---:|---:|---:|---:|:--:|",
    ]
    for row in payload["yearly"]:
        lines.append(
            f"| {row['year']} | {_pct(row['vms_return'])} | {row['vms_sharpe']:.2f} | "
            f"{_pct(-row['vms_max_drawdown'])} | {_pct(row['bh_return'])} | "
            f"{row['bh_sharpe']:.2f} | {_pct(-row['bh_max_drawdown'])} | "
            f"{'Y' if row['vms_beats_bh_sharpe'] else 'N'} |"
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
        f"- Bars (1d): {payload['bars']}; common window start index: "
        f"{payload['window_start']}",
        f"- Range: `{payload['range']}`",
        "- Query hard end: `2024-01-01 00:00 UTC` (exclusive)",
        "- Costs: 10 bps fee + 5 bps slippage per side; 25 bps stress; 5% weight "
        "quantization",
        "- Execution: closed 1d decision, next 1d open fill, ON_ENTRY, long-only "
        "weight in [0, 1]",
        f"- Registered attempts (cumulative): {payload['registered_family_attempts']}",
        "- Note: 2021 cold-year is partial for VMS (its 201-bar warmup consumes "
        "the first months); 2022-2023 are full.",
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
        raise RuntimeError("VMS discovery crossed the frozen 2024 boundary")

    factories = candidate_factories()
    factories["buy_and_hold"] = _AlwaysFull
    window_start = max(
        DogeVolatilityManagedSpot(VmsParams(median_window=365)).warmup_bars,
        DogeVolatilityManagedSpot().warmup_bars,
    )

    results = {
        name: _run(factory(), series, slippage_bps=BASE_SLIPPAGE_BPS)
        for name, factory in factories.items()
    }
    windowed = {name: _windowed(result, window_start) for name, result in results.items()}
    exposure = {
        name: _weight_path(factory, series, window_start)
        for name, factory in factories.items()
        if name != "buy_and_hold"
    }
    exposure["buy_and_hold"] = {
        "avg_exposure": 1.0,
        "min_exposure": 1.0,
        "one_way_turnover": 0.0,
    }

    stress = _windowed(
        _run(factories["vms"](), series, slippage_bps=STRESS_SLIPPAGE_BPS),
        window_start,
    )
    gross = _windowed(_run_zero_cost(factories["vms"](), series), window_start)

    vms_win = windowed["vms"]
    bh_win = windowed["buy_and_hold"]
    observed_diff = vms_win["sharpe"] - bh_win["sharpe"]
    bootstrap = _joint_block_sharpe_diff(
        vms_win["returns"], bh_win["returns"], vms_win["per_year"], observed_diff
    )
    per_bar_sharpe = (
        float(np.mean(vms_win["returns"]) / np.std(vms_win["returns"], ddof=1))
        if np.std(vms_win["returns"], ddof=1) > 0
        else 0.0
    )
    deflated = deflated_sharpe_ratio(
        per_bar_sharpe, vms_win["bars"], REGISTERED_FAMILY_ATTEMPTS
    )

    yearly = [
        _cold_year_pair(series, factories["vms"], factories["buy_and_hold"], year)
        for year in range(2021, 2024)
    ]

    gate = _gate(vms_win, stress["return"], bh_win, windowed["anti"], bootstrap, yearly)

    def _clean(record: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in record.items() if key != "returns"}

    payload: dict[str, Any] = {
        "study": "doge-volatility-managed-spot-v1",
        "stage": "discovery",
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "query_end_exclusive": DISCOVERY_END,
        "registered_family_attempts": REGISTERED_FAMILY_ATTEMPTS,
        "source_fingerprint": series_fingerprint(hourly),
        "data_fingerprint": series_fingerprint(series),
        "bars": len(series),
        "window_start": window_start,
        "range": f"{from_ms(int(series.ts[0]))}..{from_ms(int(series.ts[-1]))}",
        "windowed": {name: _clean(row) for name, row in windowed.items()},
        "exposure": exposure,
        "gross": _clean(gross),
        "stress_25bps": _clean(stress),
        "sharpe_bootstrap": bootstrap,
        "deflated_sharpe": deflated,
        "per_bar_sharpe": per_bar_sharpe,
        "yearly": yearly,
        "full_curve_summaries": {
            name: _summary(result) for name, result in results.items()
        },
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
