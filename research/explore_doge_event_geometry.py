#!/usr/bin/env python
"""Pre-2024 discovery of DOGE intraday event-path hypotheses."""

from __future__ import annotations

import datetime as dt
import json
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
HISTORY_HOURS = 90 * 24
HOLD_HOURS = 24
COOLDOWN_HOURS = 48
REGISTERED_FAMILY_ATTEMPTS = 35
OUTPUT_JSON = Path("reports/research/doge_event_geometry_discovery.json")
OUTPUT_MD = Path(
    "docs/research/doge-spot/EVENT_GEOMETRY_DISCOVERY_RESULTS_2026-07-22.md"
)


@dataclass(frozen=True)
class DacParams:
    momentum_hours: int = 24
    history_hours: int = HISTORY_HOURS
    momentum_quantile: float = 0.80
    min_effective_bars: float | None = 4.0
    max_effective_bars: float | None = None
    hold_hours: int = HOLD_HOURS
    cooldown_hours: int = COOLDOWN_HOURS
    size: float = 1.0

    def __post_init__(self) -> None:
        if min(
            self.momentum_hours,
            self.history_hours,
            self.hold_hours,
            self.cooldown_hours,
        ) < 1:
            raise ValueError("DAC horizons must be positive")
        if not 0 < self.momentum_quantile < 1:
            raise ValueError("momentum_quantile must be in (0, 1)")
        if self.min_effective_bars is not None and self.min_effective_bars < 0:
            raise ValueError("min_effective_bars must be non-negative")
        if self.max_effective_bars is not None and self.max_effective_bars <= 0:
            raise ValueError("max_effective_bars must be positive")
        if (
            self.min_effective_bars is not None
            and self.max_effective_bars is not None
            and self.min_effective_bars > self.max_effective_bars
        ):
            raise ValueError("effective-bar bounds are reversed")
        if not 0 < self.size <= 1:
            raise ValueError("spot size must be in (0, 1]")


class DogeDiffuseAccumulation:
    """Trade high 24h momentum only when its positive path is diffuse."""

    def __init__(self, params: DacParams | None = None):
        self.params = params or DacParams()
        self._target = 0.0
        self._signal_index: int | None = None
        self._cooldown_until = 0

    @property
    def name(self) -> str:
        p = self.params
        if p.max_effective_bars is not None:
            path = f"max{p.max_effective_bars:g}"
        elif p.min_effective_bars is None:
            path = "momentum-only"
        else:
            path = f"min{p.min_effective_bars:g}"
        return f"doge-dac-{p.momentum_hours}h-{path}"

    @property
    def warmup_bars(self) -> int:
        p = self.params
        return p.history_hours + p.momentum_hours + 1

    def reset(self) -> None:
        self._target = 0.0
        self._signal_index = None
        self._cooldown_until = 0

    def snapshot_state(self) -> dict[str, object]:
        return {
            "target": self._target,
            "signal_index": self._signal_index,
            "cooldown_until": self._cooldown_until,
            "params": asdict(self.params),
        }

    def on_bar(self, ctx: Context) -> Intent:
        p = self.params
        if self._target > 0:
            signal_index = self._signal_index
            if signal_index is None:
                raise RuntimeError("DAC position has no signal index")
            if ctx.index - signal_index >= p.hold_hours:
                self._target = 0.0
                self._signal_index = None
                self._cooldown_until = ctx.index + p.cooldown_hours
            return Intent(target=self._target, reason=self.name)

        if ctx.index < self._cooldown_until or float(ctx.volume(1)[-1]) <= 0:
            return Intent(target=0.0, reason=self.name)

        close = ctx.close(self.warmup_bars)
        log_close = np.log(close)
        momentum = log_close[p.momentum_hours :] - log_close[: -p.momentum_hours]
        current_momentum = float(momentum[-1])
        history = momentum[-p.history_hours - 1 : -1]
        threshold = float(np.quantile(history, p.momentum_quantile))
        recent_returns = np.diff(log_close[-p.momentum_hours - 1 :])
        positive = np.maximum(recent_returns, 0.0)
        positive_square_sum = float(np.sum(np.square(positive)))
        effective = (
            float(np.sum(positive)) ** 2 / positive_square_sum
            if positive_square_sum > 0
            else 0.0
        )
        diffuse_ok = (
            p.min_effective_bars is None or effective >= p.min_effective_bars
        )
        concentrated_ok = (
            p.max_effective_bars is None or effective <= p.max_effective_bars
        )
        if current_momentum > threshold and diffuse_ok and concentrated_ok:
            self._target = p.size
            self._signal_index = ctx.index
        return Intent(target=self._target, reason=self.name)


@dataclass(frozen=True)
class PjsParams:
    history_hours: int = HISTORY_HOURS
    jump_quantile: float = 0.975
    cluster_hours: int = 24
    confirmations: int = 2
    hold_hours: int = HOLD_HOURS
    cooldown_hours: int = COOLDOWN_HOURS
    size: float = 1.0

    def __post_init__(self) -> None:
        if min(
            self.history_hours,
            self.cluster_hours,
            self.hold_hours,
            self.cooldown_hours,
        ) < 1:
            raise ValueError("PJS horizons must be positive")
        if not 0 < self.jump_quantile < 1:
            raise ValueError("jump_quantile must be in (0, 1)")
        if self.confirmations not in (1, 2):
            raise ValueError("PJS confirmations must be one or two")
        if not 0 < self.size <= 1:
            raise ValueError("spot size must be in (0, 1]")


class DogePositiveJumpCascade:
    """Enter on a second extreme positive return inside a fixed event cluster."""

    def __init__(self, params: PjsParams | None = None):
        self.params = params or PjsParams()
        self._target = 0.0
        self._first_jump_index: int | None = None
        self._signal_index: int | None = None
        self._cooldown_until = 0

    @property
    def name(self) -> str:
        p = self.params
        suffix = "first" if p.confirmations == 1 else f"second-{p.cluster_hours}h"
        return f"doge-pjs-{suffix}"

    @property
    def warmup_bars(self) -> int:
        return self.params.history_hours + 2

    def reset(self) -> None:
        self._target = 0.0
        self._first_jump_index = None
        self._signal_index = None
        self._cooldown_until = 0

    def snapshot_state(self) -> dict[str, object]:
        return {
            "target": self._target,
            "first_jump_index": self._first_jump_index,
            "signal_index": self._signal_index,
            "cooldown_until": self._cooldown_until,
            "params": asdict(self.params),
        }

    def on_bar(self, ctx: Context) -> Intent:
        p = self.params
        if self._target > 0:
            signal_index = self._signal_index
            if signal_index is None:
                raise RuntimeError("PJS position has no signal index")
            if ctx.index - signal_index >= p.hold_hours:
                self._target = 0.0
                self._signal_index = None
                self._cooldown_until = ctx.index + p.cooldown_hours
            return Intent(target=self._target, reason=self.name)

        if ctx.index < self._cooldown_until or float(ctx.volume(1)[-1]) <= 0:
            return Intent(target=0.0, reason=self.name)

        if (
            self._first_jump_index is not None
            and ctx.index - self._first_jump_index > p.cluster_hours
        ):
            self._first_jump_index = None
            self._cooldown_until = ctx.index + p.cooldown_hours
            return Intent(target=0.0, reason=self.name)

        close = ctx.close(self.warmup_bars)
        returns = np.diff(np.log(close))
        current = float(returns[-1])
        threshold = float(np.quantile(returns[-p.history_hours - 1 : -1], p.jump_quantile))
        jump = current > threshold
        if not jump:
            return Intent(target=0.0, reason=self.name)

        if p.confirmations == 1 or self._first_jump_index is not None:
            self._target = p.size
            self._signal_index = ctx.index
            self._first_jump_index = None
        else:
            self._first_jump_index = ctx.index
        return Intent(target=self._target, reason=self.name)


def candidate_factories() -> dict[str, Callable[[], ResearchStrategy]]:
    return {
        "dac3": lambda: DogeDiffuseAccumulation(
            DacParams(min_effective_bars=3.0)
        ),
        "dac4": DogeDiffuseAccumulation,
        "dac5": lambda: DogeDiffuseAccumulation(
            DacParams(min_effective_bars=5.0)
        ),
        "momentum_only": lambda: DogeDiffuseAccumulation(
            DacParams(min_effective_bars=None)
        ),
        "concentrated": lambda: DogeDiffuseAccumulation(
            DacParams(min_effective_bars=None, max_effective_bars=2.0)
        ),
        "pjs12": lambda: DogePositiveJumpCascade(
            PjsParams(cluster_hours=12)
        ),
        "pjs24": DogePositiveJumpCascade,
        "pjs36": lambda: DogePositiveJumpCascade(
            PjsParams(cluster_hours=36)
        ),
        "first_jump": lambda: DogePositiveJumpCascade(
            PjsParams(confirmations=1)
        ),
    }


def _dac_mechanism(main: dict[str, Any], ablation: dict[str, Any]) -> bool:
    return bool(
        main["sharpe"] > ablation["sharpe"]
        or main["max_drawdown"] < ablation["max_drawdown"]
    )


def _pjs_mechanism(main: dict[str, Any], ablation: dict[str, Any]) -> bool:
    improves = (
        main["sharpe"] > ablation["sharpe"]
        or main["max_drawdown"] < ablation["max_drawdown"]
    )
    avoids_large_tradeoff = (
        main["sharpe"] >= ablation["sharpe"] - 0.10
        and main["max_drawdown"] <= ablation["max_drawdown"] + 0.10
    )
    return bool(improves and avoids_large_tradeoff)


def _gate(
    main: dict[str, Any],
    stress: dict[str, Any],
    yearly: list[dict[str, Any]],
    neighbors: list[dict[str, Any]],
    mechanism_passed: bool,
) -> dict[str, Any]:
    checks = [
        ("15 bps return > 0", main["return"] > 0),
        ("15 bps Sharpe >= 0.60", main["sharpe"] >= 0.60),
        ("MaxDD <= 40%", main["max_drawdown"] <= 0.40),
        (
            "at least two positive cold-start years",
            sum(row["return"] > 0 for row in yearly) >= 2,
        ),
        ("25 bps/side return > 0", stress["return"] > 0),
        ("return less best closed trade > 0", main["return_less_best_1"] > 0),
        ("at least twenty closed trades", main["trades"] >= 20),
        (
            "both fixed structural neighbors profitable",
            all(row["return"] > 0 for row in neighbors),
        ),
        ("mechanism ablation passed", mechanism_passed),
    ]
    return {
        "passed": all(bool(value) for _, value in checks),
        "checks": [
            {"name": name, "passed": bool(value)} for name, value in checks
        ],
    }


def _render(payload: dict[str, Any]) -> str:
    lines = [
        "# DOGE 小时事件几何发现结果 (2021-2023)",
        "",
        "> 查询在数据库层硬截止于 2024-01-01; 后续年度未读取。",
        "",
        "## 主候选",
        "",
        "| Candidate | Return | Sharpe | MaxDD | Trades | Less best 1 | 25bps | Gate |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for family in ("dac", "pjs"):
        row = payload["families"][family]
        main = row["main"]
        lines.append(
            f"| {row['main_name']} | {_pct(main['return'])} | {main['sharpe']:.2f} | "
            f"{_pct(-main['max_drawdown'])} | {main['trades']} | "
            f"{_pct(main['return_less_best_1'])} | "
            f"{_pct(row['stress_25bps']['return'])} | "
            f"{'PASS' if row['gate']['passed'] else 'FAIL'} |"
        )

    lines += [
        "",
        "## 冷启动自然年",
        "",
        "| Candidate | 2021 | 2022 | 2023 |",
        "|---|---:|---:|---:|",
    ]
    for family in ("dac", "pjs"):
        row = payload["families"][family]
        annual = " | ".join(_pct(item["return"]) for item in row["yearly"])
        lines.append(f"| {row['main_name']} | {annual} |")

    lines += [
        "",
        "## 全部固定候选与反证",
        "",
        "| Name | Return | Sharpe | MaxDD | Trades |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, row in payload["all_candidates"].items():
        lines.append(
            f"| {name} | {_pct(row['return'])} | {row['sharpe']:.2f} | "
            f"{_pct(-row['max_drawdown'])} | {row['trades']} |"
        )

    lines += ["", "## 发现门明细", ""]
    for family in ("dac", "pjs"):
        row = payload["families"][family]
        lines += [f"### {row['main_name']}", ""]
        lines.extend(
            f"- {'PASS' if check['passed'] else 'FAIL'} - {check['name']}"
            for check in row["gate"]["checks"]
        )
        lines.append("")

    lines += [
        "## Provenance",
        "",
        f"- Data fingerprint: `{payload['data_fingerprint']}`",
        f"- Bars: {payload['bars']}",
        f"- Range: `{payload['range']}`",
        "- Query hard end: `2024-01-01 00:00 UTC` (exclusive)",
        "- Registered family attempts including prior work: 35",
        "- Execution: closed 1h decision, next 1h open fill, ON_ENTRY",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    end_ms = to_ms(DISCOVERY_END)
    with Store(DB_PATH) as store:
        series = load_series(store, INSTRUMENT, "1h", end_ms=end_ms)
    if len(series) == 0:
        raise SystemExit("DOGE-USDT discovery data missing")
    if int(series.ts[-1]) >= end_ms:
        raise RuntimeError("event discovery crossed the frozen 2024 boundary")

    factories = candidate_factories()
    summaries = {
        name: _summary(_run(factory(), series, slippage_bps=BASE_SLIPPAGE_BPS))
        for name, factory in factories.items()
    }
    definitions = {
        "dac": ("dac4", ("dac3", "dac5"), "momentum_only"),
        "pjs": ("pjs24", ("pjs12", "pjs36"), "first_jump"),
    }
    families: dict[str, Any] = {}
    for family, (main_name, neighbor_names, ablation_name) in definitions.items():
        factory = factories[main_name]
        main_summary = summaries[main_name]
        stress = _summary(
            _run(factory(), series, slippage_bps=STRESS_SLIPPAGE_BPS)
        )
        yearly = [_cold_year(series, factory, year) for year in range(2021, 2024)]
        neighbors = [summaries[name] for name in neighbor_names]
        ablation = summaries[ablation_name]
        mechanism_passed = (
            _dac_mechanism(main_summary, ablation)
            if family == "dac"
            else _pjs_mechanism(main_summary, ablation)
        )
        families[family] = {
            "main_name": main_name,
            "main": main_summary,
            "stress_25bps": stress,
            "yearly": yearly,
            "neighbors": dict(zip(neighbor_names, neighbors, strict=True)),
            "ablation_name": ablation_name,
            "ablation": ablation,
            "mechanism_passed": mechanism_passed,
            "gate": _gate(
                main_summary,
                stress,
                yearly,
                neighbors,
                mechanism_passed,
            ),
        }

    payload: dict[str, Any] = {
        "study": "doge-event-geometry-v1",
        "stage": "discovery",
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "query_end_exclusive": DISCOVERY_END,
        "registered_family_attempts": REGISTERED_FAMILY_ATTEMPTS,
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
