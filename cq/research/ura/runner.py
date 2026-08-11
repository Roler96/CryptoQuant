"""Gate-ordered URA v1 discovery runner.

Run with: uv run python -m cq.research.ura.runner
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from cq.context import Context, Series
from cq.core.types import FLAT, CostModel, Intent, MarketSpec, Sizing
from cq.engine.loop import run_backtest
from cq.research.ura.analysis import (
    INITIAL_CASH,
    IntegrityError,
    UraOutcome,
    daily_returns_from_result,
    episode_results,
    performance_from_result,
    run_ura,
    validate_execution_bars,
)
from cq.research.ura.data import (
    END_MS,
    EXPECTED_COUNT,
    EXPECTED_FINGERPRINT,
    START_MS,
    load_study_data,
)
from cq.research.ura.signals import UraConfig, build_schedule, condition_funnel

PROTOCOL = "docs/research/doge-intraday/UPPER_RANGE_ACCEPTANCE_PROTOCOL_2026-08-10.md"
DEFAULT_JSON = Path("reports/research/ura_v1.json")
DEFAULT_MARKDOWN = Path(
    "docs/research/doge-intraday/UPPER_RANGE_ACCEPTANCE_RESULTS_2026-08-10.md"
)
MAIN_COSTS = CostModel(fee_bps=10.0, slippage_bps=5.0)


def _ms(year: int, month: int = 1, day: int = 1) -> int:
    return int(datetime(year, month, day, tzinfo=UTC).timestamp() * 1000)


SEGMENTS = (
    ("2021", _ms(2021), _ms(2022)),
    ("2022", _ms(2022), _ms(2023)),
    ("2023", _ms(2023), _ms(2024)),
    ("2024", _ms(2024), _ms(2025)),
    ("2025-partial", _ms(2025), END_MS),
)


@dataclass
class WindowBuyHold:
    exit_open_ms: int
    name: str = "buy-and-hold-25"
    warmup_bars: int = 0

    def reset(self) -> None:
        return None

    def on_bar(self, ctx: Context) -> Intent:
        if ctx.decision_time >= self.exit_open_ms:
            return FLAT
        return Intent(target=0.25, reason="buy-and-hold")


def run_discovery(
    db_path: Path | str = "data/cq.db", *, owner_override: bool = False
) -> dict[str, Any]:
    data = load_study_data(db_path)
    full_config = UraConfig(evaluation_start_ms=START_MS, evaluation_end_ms=END_MS)
    full_events = build_schedule(data.series, full_config)
    validate_execution_bars(data.series, full_events)

    segment_inputs: dict[str, tuple[Series, UraConfig, list]] = {}
    segment_counts: dict[str, int] = {}
    for name, start_ms, end_ms in SEGMENTS:
        series = _segment_series(data.series, start_ms, end_ms, full_config.lookback_hours)
        config = UraConfig(evaluation_start_ms=start_ms, evaluation_end_ms=end_ms)
        events = build_schedule(series, config)
        validate_execution_bars(series, events)
        segment_inputs[name] = (series, config, events)
        segment_counts[name] = len(events)

    g1_pass = len(full_events) >= 200 and all(count >= 20 for count in segment_counts.values())
    payload: dict[str, Any] = {
        "schema_version": 1,
        "study": "doge-upper-range-acceptance-v1",
        "protocol": PROTOCOL,
        "executed_at": datetime.now(UTC).isoformat(),
        "status": (
            "OPEN_BY_OWNER_OVERRIDE"
            if owner_override and not g1_pass
            else ("DISCOVERY_FAIL" if not g1_pass else "RUNNING")
        ),
        "holdout_accessed": False,
        "calibration_gate": "NOT_PRESENT_CURRENT_BRANCH",
        "owner_override": owner_override,
        "execution_gate": (
            "OPEN_BY_OWNER_OVERRIDE"
            if owner_override and not g1_pass
            else ("CLOSED_G1_CAPACITY" if not g1_pass else "OPEN")
        ),
        "data": {
            "inst_id": data.series.inst_id,
            "timeframe": data.series.timeframe,
            "start_ms": START_MS,
            "end_ms_exclusive": END_MS,
            "bars": len(data.series),
            "expected_bars": EXPECTED_COUNT,
            "raw_sha256": data.raw_fingerprint,
            "expected_sha256": EXPECTED_FINGERPRINT,
            "zero_volume_bars": data.zero_volume_count,
        },
        "config": asdict(full_config),
        "costs": {"fee_bps_per_side": 10.0, "slippage_bps_per_side": 5.0},
        "capacity": {
            "continuous_episodes": len(full_events),
            "segment_episodes": segment_counts,
            "condition_funnel": condition_funnel(data.series, full_config),
        },
        "gates": {
            "G0_integrity": "PASS",
            "G1_capacity": "PASS" if g1_pass else "FAIL",
            "G2_main_economics": "NOT_RUN",
            "G3_stress_outliers": "NOT_RUN",
            "G4_calendar": "NOT_RUN",
            "G5_bootstrap": "NOT_RUN",
            "G6_neighborhood": "NOT_RUN",
            "G7_mechanism": "NOT_RUN",
            "G8_matched_random": "NOT_RUN",
        },
        "main": None,
        "buy_and_hold_25": None,
        "calendar_main": "NOT_RUN",
        "stress": "NOT_RUN",
        "neighbors": "NOT_RUN",
        "ablations": "NOT_RUN",
        "bootstrap": "NOT_RUN",
        "matched_random": "NOT_RUN",
    }
    if not g1_pass and not owner_override:
        return payload

    main = run_ura(
        data.series,
        full_config,
        MAIN_COSTS,
        expected_events=full_events,
    )
    payload["main"] = _outcome_payload(main)
    payload["buy_and_hold_25"] = {
        name: _buy_hold_payload(series, start_ms, end_ms)
        for (name, start_ms, end_ms), (series, _, _) in zip(
            SEGMENTS, segment_inputs.values(), strict=True
        )
    }

    metrics = main.metrics
    g2_pass = (
        metrics.total_return > 0.0
        and metrics.sharpe >= 0.60
        and metrics.max_drawdown >= -0.20
    )
    payload["gates"]["G2_main_economics"] = "PASS" if g2_pass else "FAIL"
    if owner_override and not g1_pass:
        payload["status"] = (
            "OWNER_OVERRIDE_G2_PASS_CONTINUE"
            if g2_pass
            else "OWNER_OVERRIDE_G2_FAIL"
        )
    else:
        payload["status"] = "G2_PASS_CONTINUE" if g2_pass else "DISCOVERY_FAIL"
    return payload


def _outcome_payload(outcome: UraOutcome) -> dict[str, Any]:
    return {
        "metrics": asdict(outcome.metrics),
        "engine_manifest": asdict(outcome.result.manifest),
        "daily_return_observations": len(outcome.daily_returns),
        "episode_entry_times": [episode.entry_time for episode in outcome.episodes],
    }


def _buy_hold_payload(series: Series, start_ms: int, end_ms: int) -> dict[str, Any]:
    evaluation = _slice_series(series, start_ms, end_ms)
    if len(evaluation) < 2:
        raise IntegrityError("buy-and-hold segment needs at least two bars")
    result = run_backtest(
        WindowBuyHold(exit_open_ms=int(evaluation.ts[-1])),
        evaluation,
        _spot_spec(),
        initial_cash=INITIAL_CASH,
        costs=MAIN_COSTS,
        sizing=Sizing.ON_ENTRY,
        dust_fraction=0.0,
        initial_intent=Intent(target=0.25, reason="buy-and-hold"),
    )
    if result.rejections or not result.portfolio.is_flat or len(result.fills) != 2:
        raise IntegrityError("buy-and-hold baseline did not complete one round trip")
    episodes = episode_results(result)
    daily = daily_returns_from_result(result)
    return asdict(performance_from_result(result, episodes, daily))


def _spot_spec() -> MarketSpec:
    return MarketSpec(
        "DOGE-USDT",
        "spot",
        lot_size=0.0,
        min_notional=0.0,
        max_leverage=1.0,
        maintenance_margin_rate=0.0,
        contract_size=1.0,
    )


def _segment_series(series: Series, start_ms: int, end_ms: int, warmup: int) -> Series:
    start_index = int(np.searchsorted(series.ts, start_ms, side="left"))
    from_index = max(0, start_index - warmup)
    end_index = int(np.searchsorted(series.ts, end_ms, side="left"))
    return _slice_positions(series, from_index, end_index)


def _slice_series(series: Series, start_ms: int, end_ms: int) -> Series:
    start = int(np.searchsorted(series.ts, start_ms, side="left"))
    end = int(np.searchsorted(series.ts, end_ms, side="left"))
    return _slice_positions(series, start, end)


def _slice_positions(series: Series, start: int, end: int) -> Series:
    return Series(
        series.inst_id,
        series.timeframe,
        series.ts[start:end],
        series.open[start:end],
        series.high[start:end],
        series.low[start:end],
        series.close[start:end],
        series.volume[start:end],
    )


def write_outputs(
    payload: dict[str, Any],
    json_path: Path = DEFAULT_JSON,
    markdown_path: Path = DEFAULT_MARKDOWN,
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    safe = _json_safe(payload)
    json_path.write_text(
        json.dumps(safe, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(safe), encoding="utf-8")


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return "inf" if value > 0 else "-inf"
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _render_markdown(payload: dict[str, Any]) -> str:
    gates = payload["gates"]
    lines = [
        "# DOGE 上沿价格接受 (URA v1) 发现结果",
        "",
        f"- 结论: `{payload['status']}`",
        f"- 协议: `{payload['protocol']}`",
        f"- Holdout accessed: `{str(payload['holdout_accessed']).lower()}`",
        f"- Owner override: `{str(payload['owner_override']).lower()}`",
        f"- Execution gate: `{payload['execution_gate']}`",
        (
            f"- 数据: {payload['data']['bars']:,} 根 DOGE-USDT 1h; "
            f"SHA-256 `{payload['data']['raw_sha256']}`"
        ),
        "",
        "## Gates",
        "",
        "| Gate | Result |",
        "|---|---|",
    ]
    lines.extend(f"| {name} | {result} |" for name, result in gates.items())
    lines.extend(
        [
            "",
            "## Capacity",
            "",
            f"- Continuous episodes: {payload['capacity']['continuous_episodes']}",
            "- Cold-start segments: `"
            + json.dumps(payload["capacity"]["segment_episodes"], ensure_ascii=False)
            + "`",
            "- Frozen condition funnel: `"
            + json.dumps(payload["capacity"]["condition_funnel"], ensure_ascii=False)
            + "`",
        ]
    )
    if payload["main"] is not None:
        metric = payload["main"]["metrics"]
        lines.extend(
            [
                "",
                "## Main (15 bps/side)",
                "",
                "| Return | CAGR | Sharpe | MaxDD | Episodes | Win rate | PF |",
                "|---:|---:|---:|---:|---:|---:|---:|",
                "| "
                + " | ".join(
                    (
                        _pct(metric["total_return"]),
                        _pct(metric["cagr"]),
                        f"{metric['sharpe']:.4f}",
                        _pct(metric["max_drawdown"]),
                        str(metric["episodes"]),
                        _pct(metric["win_rate"]),
                        str(metric["profit_factor"]),
                    )
                )
                + " |",
                "",
                f"最长回撤: {metric['longest_drawdown_hours']} 小时; "
                f"最终未平仓: `{str(metric['open_position']).lower()}`。",
            ]
        )
    lines.extend(
        [
            "",
            "## 裁决",
            "",
            "G1/G2 任一失败后, stress、邻域、消融、bootstrap、matched-random "
            "与 holdout 均按冻结协议标记 `NOT_RUN`。",
            "",
        ]
    )
    return "\n".join(lines)


def _pct(value: float | None) -> str:
    return "null" if value is None else f"{100 * value:+.2f}%"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run frozen URA v1 discovery")
    parser.add_argument("--db", default="data/cq.db")
    parser.add_argument("--json", default=str(DEFAULT_JSON))
    parser.add_argument("--markdown", default=str(DEFAULT_MARKDOWN))
    parser.add_argument(
        "--owner-override",
        action="store_true",
        help="run G2 despite a failed G1 while preserving the failed gate",
    )
    args = parser.parse_args(argv)
    payload = run_discovery(args.db, owner_override=args.owner_override)
    write_outputs(payload, Path(args.json), Path(args.markdown))
    print(json.dumps(_json_safe(payload), ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
