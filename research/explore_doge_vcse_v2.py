#!/usr/bin/env python
"""Post-hoc exploration of a simplified DOGE VCSE v2 hypothesis."""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import numpy as np

from cq.context import series_fingerprint
from cq.data.store import Store
from cq.research.metrics import episode_returns, position_spans
from cq.research.split import from_ms
from research.audit_doge_vcse_robustness import (
    FAMILY_TRIALS,
    RESEARCH_END_MS,
    SEED,
    _block_bootstrap,
    _matched_random_null,
    _phase_series,
    _source_fingerprint,
    _year_jackknife,
)
from research.backtest_doge_vcse import (
    DB_PATH,
    INSTRUMENT,
    VcseParams,
    _run,
    _summary,
)

V2_FAMILY_TRIALS = FAMILY_TRIALS + 1
OUTPUT_JSON = Path("reports/research/doge_vcse_v2_exploration.json")
OUTPUT_MD = Path("docs/research/doge-spot/VCSE_V2_EXPLORATION_2026-07-22.md")


def _v2_params() -> VcseParams:
    return replace(VcseParams(), use_clv=False, use_volume=False)


def _pct(value: float) -> str:
    return f"{value * 100:+.2f}%"


def _render(payload: dict[str, Any]) -> str:
    gate = payload["gate"]
    lines = [
        "# DOGE VCSE v2 简化版探索 (2026-07-22)",
        "",
        "> `no_clv + no_volume` 由已见的 v1 全历史消融启发; 以下是受污染的 post-hoc "
        "exploration, 不是 OOS。",
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
        "## v1 与 v2 phase 0 对照",
        "",
        "| Version | Return | Sharpe | MaxDD | Trades | Less best 1 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for version, row in payload["comparison"].items():
        lines.append(
            f"| {version} | {_pct(row['return'])} | {row['sharpe']:.2f} | "
            f"{_pct(-row['max_drawdown'])} | {row['trades']} | "
            f"{_pct(row['return_less_best_1'])} |"
        )

    lines += [
        "",
        "## v2 4h 聚合相位",
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
        "## phase 0 成本压力",
        "",
        "| Cost/side | Return | Sharpe | MaxDD | Trades |",
        "|---:|---:|---:|---:|---:|",
    ]
    for label, row in payload["cost_stress"].items():
        lines.append(
            f"| {label} | {_pct(row['return'])} | {row['sharpe']:.2f} | "
            f"{_pct(-row['max_drawdown'])} | {row['trades']} |"
        )

    lines += [
        "",
        "## phase 0 circular block bootstrap",
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
        "## phase 0 自然年 jackknife",
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
        "## phase 0 匹配随机入场零假设",
        "",
        f"- Observed episode return: `{_pct(null['observed'])}`",
        f"- Random median: `{_pct(null['null_median'])}`",
        f"- Random P5-P95: `{_pct(null['null_p05'])}` .. `{_pct(null['null_p95'])}`",
        f"- Raw one-sided p: `{null['p_value']:.6f}`",
        f"- Sidak-adjusted p ({null['family_trials']} trials): "
        f"`{null['family_adjusted_p']:.6f}`",
        "",
        "## 解释与边界",
        "",
        "- v2删除了两个确认项, 但压缩、突破、区间扩张和全部退出规则保持不变。",
        "- 若通过, 它也只能与v1并行从零收集forward样本; 历史优势不能用于真实资金。",
        "- v2是由全历史消融启发的第18次研究尝试, 不得把结果称为独立发现。",
        "- 本轮之后不再在同一历史上继续删除过滤项或修改退出。",
        "",
        "## Provenance",
        "",
        f"- 1h data fingerprint: `{payload['source_data_fingerprint']}`",
        f"- 1h bars: {payload['source_bars']}",
        f"- Range: {payload['range']}",
        "- Input: DOGE-USDT spot OHLCV only",
        "- Protocol: `VCSE_V2_EXPLORATION_PROTOCOL_2026-07-22.md`",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    with Store(DB_PATH) as store:
        frame = store.load_ohlcv(INSTRUMENT, "1h", end_ms=RESEARCH_END_MS)
    if frame.empty:
        raise SystemExit("DOGE-USDT 1h data missing")

    params = _v2_params()
    series_by_phase = {phase: _phase_series(frame, phase) for phase in range(4)}
    results = {
        phase: _run(series, params) for phase, series in series_by_phase.items()
    }
    phases: dict[str, dict[str, Any]] = {}
    for phase, result in results.items():
        phases[str(phase)] = {
            **_summary(result),
            "bars": len(series_by_phase[phase]),
            "data_fingerprint": series_fingerprint(series_by_phase[phase]),
        }

    baseline_series = series_by_phase[0]
    baseline_result = results[0]
    v1_summary = _summary(_run(baseline_series, VcseParams()))
    stress = {
        "15 bps": phases["0"],
        "25 bps": _summary(
            _run(baseline_series, params, fee_bps=10.0, slippage_bps=15.0)
        ),
        "50 bps": _summary(
            _run(baseline_series, params, fee_bps=10.0, slippage_bps=40.0)
        ),
    }
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
        _block_bootstrap(episodes, size, seed=SEED + 100 + size)
        for size in (2, 4, 8)
    ]
    jackknife = _year_jackknife(episodes, entry_years)
    observed = float(np.prod(1.0 + np.asarray(episodes)) - 1.0)
    random_null = _matched_random_null(
        baseline_series,
        spans,
        observed,
        seed=SEED + 100,
        family_trials=V2_FAMILY_TRIALS,
    )

    phase_rows = list(phases.values())
    checks = [
        {
            "name": "all phases profitable, at least 3/4 Sharpe >= 0.60, all MaxDD <= 50%",
            "passed": all(row["return"] > 0 for row in phase_rows)
            and sum(row["sharpe"] >= 0.60 for row in phase_rows) >= 3
            and all(row["max_drawdown"] <= 0.50 for row in phase_rows),
        },
        {
            "name": "25 and 50 bps/side stress returns remain positive",
            "passed": stress["25 bps"]["return"] > 0
            and stress["50 bps"]["return"] > 0,
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
        {
            "name": "every 4h phase has at least 30 closed trades",
            "passed": all(row["trades"] >= 30 for row in phase_rows),
        },
    ]
    passed = all(check["passed"] for check in checks)
    payload: dict[str, Any] = {
        "strategy": "DogeVcse v2 post-hoc simplified",
        "source_data_fingerprint": _source_fingerprint(frame),
        "source_bars": len(frame),
        "range": f"{frame.index[0]}..{frame.index[-1]}",
        "params": asdict(params),
        "comparison": {"v1": v1_summary, "v2": phases["0"]},
        "phases": phases,
        "cost_stress": stress,
        "block_bootstrap": blocks,
        "year_jackknife": jackknife,
        "matched_random_null": random_null,
        "gate": {
            "passed": passed,
            "verdict": "EXPLORATION PASS" if passed else "EXPLORATION FAIL",
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


if __name__ == "__main__":
    raise SystemExit(main())
