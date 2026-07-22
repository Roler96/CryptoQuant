#!/usr/bin/env python
"""Descriptive probe of DOGE-USDT 1h intraday structure (2021-2023 only).

This is a DISCOVERY-stage *probe*, not a strategy discovery: it computes
descriptive statistics to decide whether any intraday structure is worth a
pre-registered forward/sequential test.  It does NOT backtest, pick parameters,
or claim an edge.  Per project discipline it queries only data before
2024-01-01, so 2024/2025/2026 remain clean for later adjudication; and it is
recorded, because an unrecorded peek cannot be corrected for.

Every close-to-close autocorrelation at 1h is contaminated by bid-ask bounce,
which manufactures spurious negative lag-1 correlation with no tradeable value.
So returns are measured two ways — close-to-close and open-to-open — and only
structure that survives at multi-hour horizons and in open-to-open terms is
worth taking to a pre-registration.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import numpy as np

from cq.context import Series, series_fingerprint
from cq.data.feed import load_series
from cq.data.store import Store
from cq.research.split import from_ms, to_ms

DB_PATH = "data/cq.db"
INSTRUMENT = "DOGE-USDT"
PROBE_END = "2024-01-01"
LAGS = (1, 2, 3, 6, 12, 24, 168)
HORIZONS = (1, 3, 6, 12, 24)
OUTPUT_JSON = Path("reports/research/doge_intraday_structure_probe.json")
OUTPUT_MD = Path(
    "docs/research/doge-spot/INTRADAY_STRUCTURE_PROBE_2026-07-22.md"
)


def _acf(x: np.ndarray, lag: int) -> float:
    if lag >= len(x):
        return 0.0
    a = x[:-lag]
    b = x[lag:]
    if np.std(a) == 0 or np.std(b) == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def _nonoverlap_reversal(log_returns: np.ndarray, horizon: int) -> dict[str, float | int]:
    """Correlation of consecutive non-overlapping k-hour cumulative returns.

    Negative => a block that rose tends to be followed by one that falls
    (short-term reversal); positive => continuation (momentum).
    """
    usable = (len(log_returns) // horizon) * horizon
    blocks = log_returns[:usable].reshape(-1, horizon).sum(axis=1)
    if len(blocks) < 3:
        return {"horizon": horizon, "blocks": len(blocks), "pearson": 0.0, "spearman": 0.0}
    past = blocks[:-1]
    future = blocks[1:]
    order_p = np.argsort(np.argsort(past))
    order_f = np.argsort(np.argsort(future))
    pearson = float(np.corrcoef(past, future)[0, 1]) if np.std(past) and np.std(future) else 0.0
    spearman = (
        float(np.corrcoef(order_p, order_f)[0, 1])
        if np.std(order_p) and np.std(order_f)
        else 0.0
    )
    return {
        "horizon": horizon,
        "blocks": len(blocks),
        "pearson": pearson,
        "spearman": spearman,
    }


def _hourly_profile(series: Series) -> list[dict[str, float | int]]:
    log_returns = np.diff(np.log(series.close))
    abs_returns = np.abs(log_returns)
    volume = series.volume[1:]
    hours = np.array(
        [dt.datetime.fromtimestamp(int(ts) / 1000, dt.UTC).hour for ts in series.ts[1:]],
        dtype=int,
    )
    rows: list[dict[str, float | int]] = []
    for hour in range(24):
        mask = hours == hour
        rows.append(
            {
                "hour": hour,
                "count": int(np.sum(mask)),
                "mean_return": float(np.mean(log_returns[mask])) if np.any(mask) else 0.0,
                "mean_abs_return": float(np.mean(abs_returns[mask])) if np.any(mask) else 0.0,
                "mean_volume": float(np.mean(volume[mask])) if np.any(mask) else 0.0,
            }
        )
    return rows


def _pct(value: float) -> str:
    return f"{value * 100:+.4f}%"


def _render(payload: dict[str, Any]) -> str:
    n = payload["observations"]
    se = payload["acf_standard_error"]
    lines = [
        "# DOGE 1h 日内结构勘察 (2021-2023)",
        "",
        "> **这是 DISCOVERY 勘察, 不是策略发现。** 只读取 2024-01-01 之前的数据;",
        "> 只计算描述性统计, 不回测/不挑参数/不宣称 edge。任何由此提出的 1h 日内",
        "> 假设, 其真正证据必须来自 2024+ 顺序验证或 2026-07-20 之后的 forward 数据。",
        "> 本次勘察消费了 discovery 自由度并已留痕。",
        "",
        f"- 观测数 (1h log returns): {n}",
        f"- ACF 标准误 ≈ 1/√N = `{se:.5f}`; |ACF| 超过约 `{2 * se:.4f}` 才统计显著",
        "  (统计显著 ≠ 可交易: 1h 存在 bid-ask bounce 噪声)。",
        "",
        "## 收益自相关 (动量 vs 反转)",
        "",
        "| Lag (h) | close-to-close | open-to-open |",
        "|---:|---:|---:|",
    ]
    for lag in LAGS:
        cc = payload["acf_close"][str(lag)]
        oo = payload["acf_open"][str(lag)]
        lines.append(f"| {lag} | {cc:+.4f} | {oo:+.4f} |")

    lines += [
        "",
        "## 波动率聚集 (|return| 自相关)",
        "",
        "| Lag (h) | ACF(|r|) |",
        "|---:|---:|",
    ]
    for lag in LAGS:
        lines.append(f"| {lag} | {payload['acf_abs'][str(lag)]:+.4f} |")

    lines += [
        "",
        "## 短期反转/延续 (非重叠 k 小时块的相邻相关)",
        "",
        "| Horizon (h) | Blocks | Pearson | Spearman |",
        "|---:|---:|---:|---:|",
    ]
    for row in payload["reversal"]:
        lines.append(
            f"| {row['horizon']} | {row['blocks']} | "
            f"{float(row['pearson']):+.4f} | {float(row['spearman']):+.4f} |"
        )

    lines += [
        "",
        "## 日内时段季节性 (按 UTC 小时)",
        "",
        "| Hour | Count | Mean return | Mean |r| (vol) | Mean volume |",
        "|---:|---:|---:|---:|---:|",
    ]
    for row in payload["hourly"]:
        lines.append(
            f"| {int(row['hour']):02d} | {row['count']} | "
            f"{_pct(float(row['mean_return']))} | {_pct(float(row['mean_abs_return']))} | "
            f"{float(row['mean_volume']):,.0f} |"
        )

    lines += [
        "",
        "## Provenance",
        "",
        f"- Data fingerprint (1h): `{payload['data_fingerprint']}`",
        f"- Bars: {payload['bars']}",
        f"- Range: `{payload['range']}`",
        "- Query hard end: `2024-01-01 00:00 UTC` (exclusive)",
        "- Nature: descriptive probe only; no strategy, no gate, no verdict",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    end_ms = to_ms(PROBE_END)
    with Store(DB_PATH) as store:
        series = load_series(store, INSTRUMENT, "1h", end_ms=end_ms)
    if len(series) == 0:
        raise SystemExit("DOGE-USDT 1h probe data missing")
    if int(series.ts[-1]) >= end_ms:
        raise RuntimeError("intraday probe crossed the frozen 2024 boundary")

    log_close = np.diff(np.log(series.close))
    log_open = np.diff(np.log(series.open))
    abs_close = np.abs(log_close)
    n = len(log_close)

    payload: dict[str, Any] = {
        "study": "doge-intraday-structure-probe",
        "stage": "discovery-probe",
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "query_end_exclusive": PROBE_END,
        "data_fingerprint": series_fingerprint(series),
        "bars": len(series),
        "observations": n,
        "acf_standard_error": 1.0 / np.sqrt(n),
        "range": f"{from_ms(int(series.ts[0]))}..{from_ms(int(series.ts[-1]))}",
        "acf_close": {str(lag): _acf(log_close, lag) for lag in LAGS},
        "acf_open": {str(lag): _acf(log_open, lag) for lag in LAGS},
        "acf_abs": {str(lag): _acf(abs_close, lag) for lag in LAGS},
        "reversal": [_nonoverlap_reversal(log_close, h) for h in HORIZONS],
        "hourly": _hourly_profile(series),
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
