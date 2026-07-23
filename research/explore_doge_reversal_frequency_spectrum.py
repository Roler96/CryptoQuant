#!/usr/bin/env python
"""Closing diagnostic: is any point on the 1h reversal frequency spectrum real?

RFS v1. Not a new candidate — a capstone over Directions C and A. The reversal
signal is real (C: +4116% gross) but dies at high frequency to cost (C) and is
indistinguishable from random at low frequency (A: Sidak p=0.49). This sweeps the
tail-quantile q — the single monotone frequency knob — across the whole spectrum
and computes a year/holding-matched random-entry p at every point. Frozen rule
(``REVERSAL_FREQUENCY_SPECTRUM_PROTOCOL_2026-07-23.md``): if the best point's
Sidak-corrected p over the 7-point sweep still exceeds 0.10, single-asset 1h
reversal is declared CLOSED, no winner cherry-picked. Single asset; 2024-capped.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import numpy as np

from cq.context import series_fingerprint
from cq.data.feed import load_series
from cq.data.store import Store
from cq.research.metrics import episode_returns, position_spans
from cq.research.split import from_ms, to_ms
from cq.research.stats import sidak_correction
from research.explore_doge_tail_reversal_1h import (
    DISCOVERY_END,
    INSTRUMENT,
    STRESS_SLIPPAGE_BPS,
    TIMEFRAME,
    DogeTailReversal,
    TcrParams,
    _matched_random_null,
    _run,
    _summary,
)

Q_GRID = (0.01, 0.025, 0.05, 0.10, 0.20, 0.35, 0.50)
FAMILY_TRIALS = len(Q_GRID)
CLOSE_THRESHOLD = 0.10
OUTPUT_JSON = Path("reports/research/doge_reversal_frequency_spectrum.json")
OUTPUT_MD = Path(
    "docs/research/doge-spot/REVERSAL_FREQUENCY_SPECTRUM_RESULTS_2026-07-23.md"
)


def _point(series: Any, q: float) -> dict[str, Any]:
    result = _run(DogeTailReversal(TcrParams(tail_quantile=q)), series)
    summary = _summary(result)
    stress = _summary(_run(DogeTailReversal(TcrParams(tail_quantile=q)), series,
                           slippage_bps=STRESS_SLIPPAGE_BPS))
    spans = position_spans(result.fills)
    episodes = episode_returns(
        result.timestamps, result.equity, result.fills, result.initial_cash
    )
    observed = float(np.prod(1.0 + np.asarray(episodes, dtype=float)) - 1.0)
    null = _matched_random_null(series, spans, observed)
    raw_p = float(null["p_value"])
    return {
        "q": q,
        "trades": summary["trades"],
        "return_15bps": summary["return"],
        "return_25bps": stress["return"],
        "sharpe": summary["sharpe"],
        "bootstrap_p05": summary["bootstrap_p05"],
        "mean_episode_return": summary["mean_episode_return"],
        "raw_p": raw_p,
        "sidak_p": sidak_correction(raw_p, FAMILY_TRIALS),
    }


def _pct(value: float) -> str:
    return f"{value * 100:+.2f}%"


def _render(payload: dict[str, Any]) -> str:
    lines = [
        "# DOGE 单资产 1h 反转频率光谱 null 诊断 (RFS v1, 2021-2023)",
        "",
        "> 数据库层硬截止 2024-01-01; 单资产。收尾诊断, 非新候选。预先承诺不挑赢家:",
        "> 取整条光谱最好点的 Sidak 校正 p, 若 > 0.10 则单资产 1h 反转判 CLOSED。",
        "",
        "## 结论",
        "",
        f"**{payload['verdict']}**",
        "",
        f"最好操作点 q={payload['best_q']}: raw p={payload['best_raw_p']:.4f}, "
        f"Sidak p (7 点) = **{payload['best_sidak_p']:.4f}** "
        f"(阈值 {CLOSE_THRESHOLD})。",
        "",
        "## 频率光谱 (每点 15bps 主, N=6, M=12, confirm=True)",
        "",
        "| q | Trades | 15bps | 25bps | Sharpe | Boot P5 | Mean ep | raw p | Sidak p |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload["spectrum"]:
        lines.append(
            f"| {row['q']:g} | {row['trades']} | {_pct(row['return_15bps'])} | "
            f"{_pct(row['return_25bps'])} | {row['sharpe']:.2f} | "
            f"{_pct(row['bootstrap_p05'])} | {_pct(row['mean_episode_return'])} | "
            f"{row['raw_p']:.4f} | {row['sidak_p']:.4f} |"
        )
    lines += [
        "",
        "光谱两端参照: C 均匀反转 (q≈每 bar) 15bps -100% (7027 笔, 成本墙);",
        "本表 q→0.01 是 A 侧的极稀疏端。",
        "",
        "## Provenance",
        "",
        f"- DOGE fingerprint: `{payload['fingerprint']}`",
        f"- Bars: {payload['bars']}",
        f"- Range: `{payload['range']}`",
        "- Costs: 10 bps fee + 5 bps slippage per side; 25 bps stress",
        "- Mechanism: frozen DogeTailReversal (A), only q swept",
        "- Protocol: `REVERSAL_FREQUENCY_SPECTRUM_PROTOCOL_2026-07-23.md`",
        "",
    ]
    if payload["closed"]:
        lines += [
            "整条频率光谱上没有任一操作点在族修正后与随机可分。**单资产 1h 反转判定 CLOSED**:",
            "信号毛值真实但要么被成本吞没、要么与运气不可分。不挑赢家, 不开 v2, 不读 2024。",
            "与 15+ 择时机制并列的同一堵功效墙。",
            "",
        ]
    else:
        lines += [
            f"存在操作点 (q={payload['best_q']}) 族修正后 p<=0.10, 记为线索但本诊断不直接晋级;",
            "须另开独立预注册版本、用未被本次扫描消费的证据重新检验。",
            "",
        ]
    return "\n".join(lines)


def main() -> int:
    end_ms = to_ms(DISCOVERY_END)
    with Store("data/cq.db") as store:
        series = load_series(store, INSTRUMENT, TIMEFRAME, end_ms=end_ms)
    if len(series) == 0:
        raise SystemExit("RFS diagnostic market data missing")
    if int(series.ts[-1]) >= end_ms:
        raise RuntimeError("RFS diagnostic query crossed the frozen 2024 boundary")

    spectrum = [_point(series, q) for q in Q_GRID]
    best = min(spectrum, key=lambda row: row["sidak_p"])
    closed = best["sidak_p"] > CLOSE_THRESHOLD
    verdict = (
        "CLOSED: 单资产 1h 反转处处 null"
        if closed
        else f"LEAD at q={best['q']:g} (须独立复核, 不直接晋级)"
    )
    payload: dict[str, Any] = {
        "study": "doge-reversal-frequency-spectrum-v1",
        "stage": "diagnostic",
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "query_end_exclusive": DISCOVERY_END,
        "family_trials": FAMILY_TRIALS,
        "close_threshold": CLOSE_THRESHOLD,
        "fingerprint": series_fingerprint(series),
        "bars": len(series),
        "range": f"{from_ms(int(series.ts[0]))}..{from_ms(int(series.ts[-1]))}",
        "spectrum": spectrum,
        "best_q": best["q"],
        "best_raw_p": best["raw_p"],
        "best_sidak_p": best["sidak_p"],
        "closed": closed,
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
