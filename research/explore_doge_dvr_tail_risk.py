#!/usr/bin/env python
"""Pre-2024 discovery of the risk-managed DOGE DVR strategy."""

from __future__ import annotations

import datetime as dt
import json
import math
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from cq.context import Context, series_fingerprint
from cq.core.types import Intent
from cq.data.feed import load_series
from cq.data.store import Store
from cq.research.split import from_ms, to_ms
from research.explore_doge_directional_regimes import (
    BASE_SLIPPAGE_BPS,
    DB_PATH,
    INSTRUMENT,
    STRESS_SLIPPAGE_BPS,
    ResearchStrategy,
    _cold_year,
    _pct,
    _run,
    _summary,
)

DISCOVERY_END = "2024-01-01"
REGISTERED_FAMILY_ATTEMPTS = 39
OUTPUT_JSON = Path("reports/research/doge_dvr_tail_risk_discovery.json")
OUTPUT_MD = Path(
    "docs/research/doge-spot/DVR_TAIL_RISK_DISCOVERY_RESULTS_2026-07-22.md"
)


@dataclass(frozen=True)
class DvrTailParams:
    horizon: int = 28
    entry_share: float = 0.60
    exit_share: float = 0.45
    size: float = 0.25
    trail_drawdown: float | None = 0.25

    def __post_init__(self) -> None:
        if self.horizon < 2:
            raise ValueError("horizon must be at least two bars")
        if not 0 <= self.exit_share < self.entry_share <= 1:
            raise ValueError("DVR thresholds must satisfy 0 <= exit < entry <= 1")
        if not 0 < self.size <= 1:
            raise ValueError("spot size must be in (0, 1]")
        if self.trail_drawdown is not None and not 0 < self.trail_drawdown < 1:
            raise ValueError("trail_drawdown must be in (0, 1)")


class DogeDvrTailRisk:
    """Quarter-weight DVR with a close-confirmed peak drawdown lock."""

    def __init__(self, params: DvrTailParams | None = None):
        self.params = params or DvrTailParams()
        self._target = 0.0
        self._peak_close = 0.0
        self._armed = True

    @property
    def name(self) -> str:
        trail = (
            "none"
            if self.params.trail_drawdown is None
            else f"{self.params.trail_drawdown * 100:g}"
        )
        return f"doge-dvr-tail-{trail}-size{self.params.size:g}"

    @property
    def warmup_bars(self) -> int:
        return self.params.horizon + 1

    def reset(self) -> None:
        self._target = 0.0
        self._peak_close = 0.0
        self._armed = True

    def snapshot_state(self) -> dict[str, object]:
        return {
            "target": self._target,
            "peak_close": self._peak_close,
            "armed": self._armed,
            "params": asdict(self.params),
        }

    def on_bar(self, ctx: Context) -> Intent:
        p = self.params
        close = ctx.close(self.warmup_bars)
        log_returns = np.diff(np.log(close))
        total_variance = float(np.sum(np.square(log_returns)))
        upside_variance = float(
            np.sum(np.square(np.maximum(log_returns, 0.0)))
        )
        share = upside_variance / total_variance if total_variance > 0 else 0.5
        momentum = float(math.log(close[-1] / close[0]))
        current = float(close[-1])
        original_exit = share <= p.exit_share or momentum <= 0

        if self._target > 0:
            self._peak_close = max(self._peak_close, current)
            trail_exit = (
                p.trail_drawdown is not None
                and current <= self._peak_close * (1.0 - p.trail_drawdown)
            )
            if original_exit or trail_exit:
                self._target = 0.0
                self._peak_close = 0.0
                self._armed = bool(original_exit)
        elif not self._armed:
            if original_exit:
                self._armed = True
        elif share >= p.entry_share and momentum > 0:
            self._target = p.size
            self._peak_close = current

        return Intent(target=self._target, reason=self.name)


def candidate_factories() -> dict[str, Callable[[], ResearchStrategy]]:
    return {
        "trail20": lambda: DogeDvrTailRisk(
            DvrTailParams(trail_drawdown=0.20)
        ),
        "trail25": DogeDvrTailRisk,
        "trail30": lambda: DogeDvrTailRisk(
            DvrTailParams(trail_drawdown=0.30)
        ),
        "no_trail": lambda: DogeDvrTailRisk(
            DvrTailParams(trail_drawdown=None)
        ),
    }


def _gate(
    main: dict[str, Any],
    stress: dict[str, Any],
    yearly: list[dict[str, Any]],
    neighbors: list[dict[str, Any]],
    no_trail: dict[str, Any],
) -> dict[str, Any]:
    checks = [
        ("15 bps return > 0", main["return"] > 0),
        ("15 bps Sharpe >= 0.60", main["sharpe"] >= 0.60),
        ("MaxDD <= 30%", main["max_drawdown"] <= 0.30),
        (
            "at least two positive cold-start years",
            sum(row["return"] > 0 for row in yearly) >= 2,
        ),
        ("25 bps/side return > 0", stress["return"] > 0),
        ("return less best closed trade > 0", main["return_less_best_1"] > 0),
        ("at least six closed trades", main["trades"] >= 6),
        (
            "20% and 30% fixed trail neighbors profitable",
            all(row["return"] > 0 for row in neighbors),
        ),
        (
            "trail strictly lowers MaxDD versus no-trail and remains profitable",
            main["max_drawdown"] < no_trail["max_drawdown"] and main["return"] > 0,
        ),
    ]
    return {
        "passed": all(bool(value) for _, value in checks),
        "checks": [
            {"name": name, "passed": bool(value)} for name, value in checks
        ],
    }


def _render(payload: dict[str, Any]) -> str:
    main = payload["main"]
    stress = payload["stress_25bps"]
    lines = [
        "# DOGE DVR 尾部风险版本发现结果 (2021-2023)",
        "",
        "> 查询在数据库层硬截止于 2024-01-01; 后续年度未读取。",
        "",
        "## 主版本",
        "",
        "| Return | Sharpe | MaxDD | Trades | Less best 1 | 25bps | Gate |",
        "|---:|---:|---:|---:|---:|---:|---|",
        (
            f"| {_pct(main['return'])} | {main['sharpe']:.2f} | "
            f"{_pct(-main['max_drawdown'])} | {main['trades']} | "
            f"{_pct(main['return_less_best_1'])} | {_pct(stress['return'])} | "
            f"{'PASS' if payload['gate']['passed'] else 'FAIL'} |"
        ),
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
        "## 风险邻域与反证",
        "",
        "| Version | Return | Sharpe | MaxDD | Trades | Less best 1 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, row in payload["all_candidates"].items():
        lines.append(
            f"| {name} | {_pct(row['return'])} | {row['sharpe']:.2f} | "
            f"{_pct(-row['max_drawdown'])} | {row['trades']} | "
            f"{_pct(row['return_less_best_1'])} |"
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
        f"- Data fingerprint: `{payload['data_fingerprint']}`",
        f"- Bars: {payload['bars']}",
        f"- Range: `{payload['range']}`",
        "- Query hard end: `2024-01-01 00:00 UTC` (exclusive)",
        "- Registered family attempts including prior work: 39",
        "- Execution: closed 1d decision, next 1d open fill, ON_ENTRY",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    end_ms = to_ms(DISCOVERY_END)
    with Store(DB_PATH) as store:
        series = load_series(store, INSTRUMENT, "1d", end_ms=end_ms)
    if len(series) == 0:
        raise SystemExit("DOGE-USDT discovery data missing")
    if int(series.ts[-1]) >= end_ms:
        raise RuntimeError("DVR tail-risk discovery crossed the frozen 2024 boundary")

    factories = candidate_factories()
    summaries = {
        name: _summary(_run(factory(), series, slippage_bps=BASE_SLIPPAGE_BPS))
        for name, factory in factories.items()
    }
    main_summary = summaries["trail25"]
    stress = _summary(
        _run(
            factories["trail25"](),
            series,
            slippage_bps=STRESS_SLIPPAGE_BPS,
        )
    )
    yearly = [
        _cold_year(series, factories["trail25"], year)
        for year in range(2021, 2024)
    ]
    gate = _gate(
        main_summary,
        stress,
        yearly,
        [summaries["trail20"], summaries["trail30"]],
        summaries["no_trail"],
    )
    payload: dict[str, Any] = {
        "study": "doge-dvr-tail-risk-v1",
        "stage": "discovery",
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "query_end_exclusive": DISCOVERY_END,
        "registered_family_attempts": REGISTERED_FAMILY_ATTEMPTS,
        "params": asdict(DvrTailParams()),
        "data_fingerprint": series_fingerprint(series),
        "bars": len(series),
        "range": f"{from_ms(int(series.ts[0]))}..{from_ms(int(series.ts[-1]))}",
        "main": main_summary,
        "stress_25bps": stress,
        "yearly": yearly,
        "all_candidates": summaries,
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
