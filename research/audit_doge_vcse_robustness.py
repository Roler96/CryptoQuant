#!/usr/bin/env python
"""Robustness audit for the frozen DOGE VCSE v1 strategy.

The protocol was fixed before these calculations in
``docs/research/doge-spot/VCSE_ROBUSTNESS_PROTOCOL_2026-07-22.md``.
This module audits v1; it does not tune or replace any strategy parameter.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from cq.context import Series, series_fingerprint
from cq.core.types import CostModel
from cq.data.store import Store
from cq.research.metrics import episode_returns, position_spans
from cq.research.split import from_ms
from cq.research.stats import sidak_correction
from research.backtest_doge_vcse import (
    BASE_FEE_BPS,
    BASE_SLIPPAGE_BPS,
    DB_PATH,
    INSTRUMENT,
    VcseParams,
    _run,
    _summary,
)

SAMPLES = 10_000
SEED = 20260722
FAMILY_TRIALS = 17
# Exclusive 1h boundary of the dataset that v1 originally consumed. The live
# database keeps growing; an audit must not silently grow with it on rerun.
RESEARCH_END_MS = int(
    dt.datetime(2026, 7, 20, 7, tzinfo=dt.UTC).timestamp() * 1000
)
OUTPUT_JSON = Path("reports/research/doge_vcse_robustness.json")
OUTPUT_MD = Path("docs/research/doge-spot/VCSE_ROBUSTNESS_2026-07-22.md")

_AGGREGATION = {
    "open": "first",
    "high": "max",
    "low": "min",
    "close": "last",
    "volume": "sum",
}


def _phase_series(frame: pd.DataFrame, phase_hours: int) -> Series:
    """Aggregate 1h bars into complete 4h groups at one UTC phase."""
    if phase_hours not in range(4):
        raise ValueError("phase_hours must be one of 0, 1, 2, 3")
    grouped = frame.resample(
        pd.Timedelta(hours=4),
        origin="epoch",
        offset=f"{phase_hours}h",
        label="left",
        closed="left",
    )
    aggregated = grouped.agg(_AGGREGATION)
    counts = grouped.size().to_numpy()
    complete = aggregated.loc[counts == 4]
    return Series(
        inst_id=INSTRUMENT,
        timeframe="4h",
        ts=(complete.index.astype("int64") // 1_000_000).to_numpy(),
        open=complete["open"].to_numpy(dtype=float),
        high=complete["high"].to_numpy(dtype=float),
        low=complete["low"].to_numpy(dtype=float),
        close=complete["close"].to_numpy(dtype=float),
        volume=complete["volume"].to_numpy(dtype=float),
    )


def _block_bootstrap(
    returns: list[float] | np.ndarray,
    block_size: int,
    samples: int = SAMPLES,
    seed: int = SEED,
) -> dict[str, float | int]:
    """Circular moving-block bootstrap preserving local trade order."""
    values = np.asarray(returns, dtype=float)
    if block_size < 1:
        raise ValueError("block_size must be positive")
    if samples < 1:
        raise ValueError("samples must be positive")
    if len(values) == 0:
        return {
            "block_size": block_size,
            "samples": samples,
            "observed": 0.0,
            "probability_of_loss": 0.0,
            "p05": 0.0,
            "median": 0.0,
            "p95": 0.0,
        }

    blocks = math.ceil(len(values) / block_size)
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, len(values), size=(samples, blocks))
    offsets = np.arange(block_size)
    indexes = ((starts[:, :, None] + offsets) % len(values)).reshape(samples, -1)
    draws = values[indexes[:, : len(values)]]
    totals = np.prod(1.0 + draws, axis=1) - 1.0
    return {
        "block_size": block_size,
        "samples": samples,
        "observed": float(np.prod(1.0 + values) - 1.0),
        "probability_of_loss": float(np.mean(totals < 0)),
        "p05": float(np.percentile(totals, 5)),
        "median": float(np.median(totals)),
        "p95": float(np.percentile(totals, 95)),
    }


def _year_jackknife(
    returns: list[float] | np.ndarray, entry_years: list[int] | np.ndarray
) -> list[dict[str, float | int]]:
    values = np.asarray(returns, dtype=float)
    years = np.asarray(entry_years, dtype=int)
    if len(values) != len(years):
        raise ValueError("returns and entry_years must have equal length")
    output: list[dict[str, float | int]] = []
    for year in sorted(set(years.tolist())):
        keep = years != year
        output.append(
            {
                "removed_year": int(year),
                "removed_trades": int(np.sum(~keep)),
                "remaining_trades": int(np.sum(keep)),
                "return": float(np.prod(1.0 + values[keep]) - 1.0),
            }
        )
    return output


def _matched_random_null(
    series: Series,
    spans: list[tuple[int, int | None]],
    observed: float,
    samples: int = SAMPLES,
    seed: int = SEED,
    family_trials: int = FAMILY_TRIALS,
    costs: CostModel | None = None,
) -> dict[str, float | int]:
    """Random entries matched on entry year, holding bars and round-trip costs."""
    if samples < 1:
        raise ValueError("samples must be positive")
    if family_trials < 1:
        raise ValueError("family_trials must be positive")
    costs = costs or CostModel(
        fee_bps=BASE_FEE_BPS, slippage_bps=BASE_SLIPPAGE_BPS
    )
    index_of = {int(ts): index for index, ts in enumerate(series.ts)}
    years = np.array([int(from_ms(int(ts))[:4]) for ts in series.ts], dtype=int)
    indexes = np.arange(len(series), dtype=int)
    rng = np.random.default_rng(seed)
    totals = np.ones(samples, dtype=float)

    for entry_ts, exit_ts in spans:
        entry_index = index_of[int(entry_ts)]
        exit_index = len(series) - 1 if exit_ts is None else index_of[int(exit_ts)]
        holding_bars = exit_index - entry_index
        if holding_bars < 1:
            raise ValueError("every matched episode must hold for at least one bar")
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
            raise ValueError(
                f"no random candidates for {entry_ts=} and {holding_bars=}"
            )
        starts = rng.choice(candidates, size=samples, replace=True)
        exits = starts + holding_bars
        totals *= _round_trip_factors(
            series.open[starts], series.open[exits], costs
        )

    null_returns = totals - 1.0
    exceedances = int(np.sum(null_returns >= observed))
    p_value = (exceedances + 1) / (samples + 1)
    return {
        "samples": samples,
        "trades_matched": len(spans),
        "family_trials": family_trials,
        "observed": observed,
        "null_p05": float(np.percentile(null_returns, 5)),
        "null_median": float(np.median(null_returns)),
        "null_p95": float(np.percentile(null_returns, 95)),
        "p_value": p_value,
        "family_adjusted_p": sidak_correction(p_value, family_trials),
    }


def _round_trip_factors(
    entry_open: np.ndarray, exit_open: np.ndarray, costs: CostModel
) -> np.ndarray:
    fee = costs.fee_bps / 10_000
    slippage = costs.slippage_bps / 10_000
    cost_factor = ((1 - slippage) * (1 - fee)) / (
        (1 + slippage) * (1 + fee)
    )
    return np.asarray(exit_open / entry_open * cost_factor, dtype=float)


def _pct(value: float) -> str:
    return f"{value * 100:+.2f}%"


def _render(payload: dict[str, Any]) -> str:
    gate = payload["gate"]
    lines = [
        "# DOGE VCSE v1 稳健性审计 (2026-07-22)",
        "",
        "> 本报告执行预先冻结的稳健性协议; 历史已被访问, 不是 OOS。",
        "",
        "## 结论",
        "",
        f"**{gate['verdict']}**",
        "",
    ]
    lines.extend(
        f"- {'PASS' if check['passed'] else 'FAIL'} - {check['name']}"
        for check in gate["checks"]
    )
    lines += [
        "",
        "## 4h 聚合相位",
        "",
        "| Phase | Return | Sharpe | MaxDD | Trades | Less best 1 |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for phase, row in payload["phases"].items():
        lines.append(
            f"| {phase}h | {_pct(row['return'])} | {row['sharpe']:.2f} | "
            f"{_pct(-row['max_drawdown'])} | {row['trades']} | "
            f"{_pct(row['return_less_best_1'])} |"
        )

    lines += [
        "",
        "## Circular block bootstrap (phase 0)",
        "",
        "| Block trades | P(loss) | P5 | Median | P95 |",
        "|---:|---:|---:|---:|---:|",
    ]
    for row in payload["block_bootstrap"]:
        lines.append(
            f"| {row['block_size']} | {_pct(row['probability_of_loss'])} | "
            f"{_pct(row['p05'])} | {_pct(row['median'])} | {_pct(row['p95'])} |"
        )

    lines += [
        "",
        "## 自然年 jackknife (phase 0)",
        "",
        "| Removed entry year | Removed trades | Remaining return |",
        "|---:|---:|---:|",
    ]
    for row in payload["year_jackknife"]:
        lines.append(
            f"| {row['removed_year']} | {row['removed_trades']} | "
            f"{_pct(row['return'])} |"
        )

    null = payload["matched_random_null"]
    lines += [
        "",
        "## 匹配随机入场零假设 (phase 0)",
        "",
        f"- VCSE observed episode return: `{_pct(null['observed'])}`",
        f"- Random median: `{_pct(null['null_median'])}`",
        f"- Random P5-P95: `{_pct(null['null_p05'])}` .. `{_pct(null['null_p95'])}`",
        f"- Raw one-sided p: `{null['p_value']:.6f}`",
        f"- Sidak-adjusted p ({null['family_trials']} trials): "
        f"`{null['family_adjusted_p']:.6f}`",
        "",
        "## 证据边界",
        "",
        "- 所有数字仍来自已被研究过的同一段历史, 只能削弱或保留假设, 不能创造 OOS 证据。",
        "- 相位审计改变信号观察窗口, 也会改变具体交易; 它检验的是时间锚定敏感性。",
        "- block bootstrap只保留交易序列的局部聚集, 不能模拟价格制度永久改变。",
        "- 随机零假设控制入场年份和持仓时长, 但未控制月度市场状态。",
        "- v1规则保持冻结; 任何简化版必须作为新的、受污染的探索假设单独登记。",
        "",
        "## Provenance",
        "",
        f"- 1h data fingerprint: `{payload['source_data_fingerprint']}`",
        f"- 1h bars: {payload['source_bars']}",
        f"- Range: {payload['range']}",
        "- Input: DOGE-USDT spot OHLCV only",
        "- Protocol: `VCSE_ROBUSTNESS_PROTOCOL_2026-07-22.md`",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    with Store(DB_PATH) as store:
        frame = store.load_ohlcv(INSTRUMENT, "1h", end_ms=RESEARCH_END_MS)
    if frame.empty:
        raise SystemExit("DOGE-USDT 1h data missing")

    series_by_phase = {phase: _phase_series(frame, phase) for phase in range(4)}
    results = {
        phase: _run(series, VcseParams()) for phase, series in series_by_phase.items()
    }
    phases: dict[str, dict[str, Any]] = {}
    for phase, result in results.items():
        phases[str(phase)] = {
            **_summary(result),
            "bars": len(series_by_phase[phase]),
            "data_fingerprint": series_fingerprint(series_by_phase[phase]),
        }

    baseline_result = results[0]
    baseline_series = series_by_phase[0]
    episodes = episode_returns(
        baseline_result.timestamps,
        baseline_result.equity,
        baseline_result.fills,
        baseline_result.initial_cash,
    )
    spans = position_spans(baseline_result.fills)
    if len(episodes) != len(spans):
        raise RuntimeError("episode returns and position spans disagree")
    entry_years = [int(from_ms(entry_ts)[:4]) for entry_ts, _ in spans]
    blocks = [
        _block_bootstrap(episodes, size, seed=SEED + size) for size in (2, 4, 8)
    ]
    jackknife = _year_jackknife(episodes, entry_years)
    observed_episode_return = float(np.prod(1.0 + np.asarray(episodes)) - 1.0)
    random_null = _matched_random_null(
        baseline_series, spans, observed_episode_return
    )

    phase_rows = list(phases.values())
    checks = [
        {
            "name": "all four 4h phases are profitable and at least 3/4 Sharpe >= 0.60",
            "passed": all(row["return"] > 0 for row in phase_rows)
            and sum(row["sharpe"] >= 0.60 for row in phase_rows) >= 3,
        },
        {
            "name": "all four 4h phases have MaxDD <= 50%",
            "passed": all(row["max_drawdown"] <= 0.50 for row in phase_rows),
        },
        {
            "name": "block bootstrap P5 is positive at sizes 2, 4 and 8",
            "passed": all(row["p05"] > 0 for row in blocks),
        },
        {
            "name": "every entry-year jackknife return is positive",
            "passed": all(row["return"] > 0 for row in jackknife),
        },
        {
            "name": "matched random-entry family-adjusted p < 0.05",
            "passed": random_null["family_adjusted_p"] < 0.05,
        },
    ]
    passed = all(check["passed"] for check in checks)
    payload: dict[str, Any] = {
        "strategy": "DogeVcse v1",
        "source_data_fingerprint": _source_fingerprint(frame),
        "source_bars": len(frame),
        "range": f"{frame.index[0]}..{frame.index[-1]}",
        "params": asdict(VcseParams()),
        "phases": phases,
        "block_bootstrap": blocks,
        "year_jackknife": jackknife,
        "matched_random_null": random_null,
        "gate": {
            "passed": passed,
            "verdict": "ROBUSTNESS PASS" if passed else "ROBUSTNESS FAIL",
            "checks": checks,
        },
    }
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    OUTPUT_MD.write_text(_render(payload), encoding="utf-8")
    print(_render(payload))
    print(f"JSON: {OUTPUT_JSON}")
    print(f"REPORT: {OUTPUT_MD}")
    return 0 if passed else 2


def _source_fingerprint(frame: pd.DataFrame) -> str:
    """Fingerprint the exact 1h columns from which all four phases derive."""
    source = Series(
        inst_id=INSTRUMENT,
        timeframe="1h",
        ts=(frame.index.astype("int64") // 1_000_000).to_numpy(),
        open=frame["open"].to_numpy(dtype=float),
        high=frame["high"].to_numpy(dtype=float),
        low=frame["low"].to_numpy(dtype=float),
        close=frame["close"].to_numpy(dtype=float),
        volume=frame["volume"].to_numpy(dtype=float),
    )
    return series_fingerprint(source)


if __name__ == "__main__":
    raise SystemExit(main())
