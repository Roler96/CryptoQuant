"""Gate-ordered SPDP v2 discovery runner.

Run with: uv run python -m cq.research.spdp.runner
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import shutil
import subprocess
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from cq.context import Series
from cq.core.types import CostModel
from cq.research.spdp.analysis import IntegrityError, SpdpOutcome, run_spdp, validate_execution_bars
from cq.research.spdp.data import StudyData, load_study_data
from cq.research.spdp.signals import WINDOW_BARS, SpdpConfig, build_schedule, condition_funnel


def _ms(year: int, month: int = 1, day: int = 1) -> int:
    return int(datetime(year, month, day, tzinfo=UTC).timestamp() * 1000)


START_MS = _ms(2021)
END_MS = _ms(2025, 6, 1)
EXPECTED_COUNT = 38_688
EXPECTED_SPOT_SHA256 = "11459117bfa9dcd09d942e9f0b4dfaf29c5e8bbb92272147cbbf8ba7bb28427f"
EXPECTED_SWAP_SHA256 = "1e0e3be7e9a88af2e9e36757eb0b697e1f8b81a54c98c04d5123d702c8d90f98"
PROTOCOLS = (
    "docs/research/doge-intraday/SPOT_PARTICIPATION_DEMAND_PERSISTENCE_PROTOCOL_2026-08-11.md",
    "docs/research/doge-intraday/SPOT_PARTICIPATION_DEMAND_PERSISTENCE_PROTOCOL_V2_2026-08-11.md",
)
DEFAULT_JSON = Path("reports/research/spdp_v2.json")
DEFAULT_MARKDOWN = Path(
    "docs/research/doge-intraday/SPOT_PARTICIPATION_DEMAND_PERSISTENCE_RESULTS_2026-08-11.md"
)
MAIN_COSTS = CostModel(fee_bps=10.0, slippage_bps=5.0)
SEGMENTS = (
    ("2021", _ms(2021), _ms(2022)),
    ("2022", _ms(2022), _ms(2023)),
    ("2023", _ms(2023), _ms(2024)),
    ("2024", _ms(2024), _ms(2025)),
    ("2025-partial", _ms(2025), END_MS),
)


def run_discovery(db_path: Path | str = "data/cq.db") -> dict[str, Any]:
    data = load_study_data(
        db_path,
        START_MS,
        END_MS,
        expected_count=EXPECTED_COUNT,
        expected_spot_fingerprint=EXPECTED_SPOT_SHA256,
        expected_swap_fingerprint=EXPECTED_SWAP_SHA256,
    )
    full_config = SpdpConfig(
        evaluation_start_ms=START_MS,
        evaluation_end_ms=END_MS,
    )
    full_events = build_schedule(data, full_config)
    validate_execution_bars(data, full_events)

    segment_inputs: dict[str, tuple[StudyData, SpdpConfig, list]] = {}
    segment_counts: dict[str, int] = {}
    segment_funnels: dict[str, dict[str, int]] = {}
    for name, start_ms, end_ms in SEGMENTS:
        segment = _segment_data(data, start_ms, end_ms)
        config = SpdpConfig(
            evaluation_start_ms=start_ms,
            evaluation_end_ms=end_ms,
        )
        events = build_schedule(segment, config)
        validate_execution_bars(segment, events)
        segment_inputs[name] = (segment, config, events)
        segment_counts[name] = len(events)
        segment_funnels[name] = condition_funnel(segment, config)

    g1_pass = len(full_events) >= 80 and all(
        count >= 8 for count in segment_counts.values()
    )
    payload: dict[str, Any] = {
        "schema_version": 2,
        "study": "doge-spot-participation-demand-persistence-v2",
        "protocols": list(PROTOCOLS),
        "executed_at": datetime.now(UTC).isoformat(),
        "status": "RUNNING" if g1_pass else "DISCOVERY_FAIL",
        "holdout_accessed": False,
        "worktree_status": _worktree_status(),
        "tests": {
            "command": "uv run pytest -q tests/test_spdp_*.py",
            "passed": None,
            "status": "NOT_RUN_BY_RUNNER",
        },
        "tool_versions": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pytest": importlib.metadata.version("pytest"),
        },
        "data": {
            "start_ms": START_MS,
            "end_ms_exclusive": END_MS,
            "bars_per_leg": len(data.spot),
            "expected_bars_per_leg": EXPECTED_COUNT,
            "spot_raw_sha256": data.spot_raw_fingerprint,
            "swap_raw_sha256": data.swap_raw_fingerprint,
            "expected_spot_sha256": EXPECTED_SPOT_SHA256,
            "expected_swap_sha256": EXPECTED_SWAP_SHA256,
            "spot_degenerate_bars": _degenerate_count(data.spot_qv),
            "swap_degenerate_bars": _degenerate_count(data.swap_qv),
            "aux_fingerprints": data.aux_fingerprints,
        },
        "config": asdict(full_config),
        "costs": {
            "fee_bps_per_side": MAIN_COSTS.fee_bps,
            "slippage_bps_per_side": MAIN_COSTS.slippage_bps,
        },
        "capacity": {
            "continuous_episodes": len(full_events),
            "segment_episodes": segment_counts,
            "condition_funnel": condition_funnel(data, full_config),
            "segment_condition_funnels": segment_funnels,
            "episode_schedule": [
                {
                    "decision_time": int(data.spot.ts[event.decision_index]),
                    "entry_time": int(data.spot.ts[event.entry_index]),
                    "exit_time": int(data.spot.ts[event.exit_index]),
                }
                for event in full_events
            ],
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
        "calendar_main": "NOT_RUN",
        "buy_and_hold_25": "NOT_RUN",
        "stress": "NOT_RUN",
        "static_suppression": "NOT_RUN",
        "concentration": "NOT_RUN",
        "bootstrap": "NOT_RUN",
        "neighbors": "NOT_RUN",
        "ablations": "NOT_RUN",
        "matched_random": "NOT_RUN",
    }
    if not g1_pass:
        return payload

    main = run_spdp(data, full_config, MAIN_COSTS, expected_events=full_events)
    payload["main"] = _outcome_payload(main)
    g2_pass = (
        main.metrics.total_return > 0.0
        and main.metrics.sharpe >= 0.60
        and main.metrics.max_drawdown >= -0.20
    )
    payload["gates"]["G2_main_economics"] = "PASS" if g2_pass else "FAIL"
    payload["status"] = "G2_PASS_CONTINUE" if g2_pass else "DISCOVERY_FAIL"
    return payload


def _outcome_payload(outcome: SpdpOutcome) -> dict[str, Any]:
    return {
        "metrics": asdict(outcome.metrics),
        "engine_manifest": asdict(outcome.result.manifest),
        "daily_return_observations": len(outcome.daily_returns),
        "episodes": [asdict(episode) for episode in outcome.episodes],
    }


def _degenerate_count(series: Series) -> int:
    return int(np.count_nonzero((series.volume <= 0.0) | (series.close <= 0.0)))


def _worktree_status() -> dict[str, Any]:
    git = shutil.which("git")
    if git is None:
        return {
            "command": "git status --short --branch",
            "exit_code": None,
            "lines": ["git executable not found"],
        }
    completed = subprocess.run(  # noqa: S603 - resolved git, fixed read-only args
        [git, "status", "--short", "--branch"],
        check=False,
        capture_output=True,
        text=True,
    )
    lines = completed.stdout.rstrip().splitlines()
    return {
        "command": "git status --short --branch",
        "exit_code": completed.returncode,
        "lines": lines,
    }


def _segment_data(data: StudyData, start_ms: int, end_ms: int) -> StudyData:
    start_index = int(np.searchsorted(data.spot.ts, start_ms, side="left"))
    from_index = max(0, start_index - (WINDOW_BARS - 1))
    end_index = int(np.searchsorted(data.spot.ts, end_ms, side="left"))
    return StudyData(
        spot=_slice_series(data.spot, from_index, end_index),
        swap=_slice_series(data.swap, from_index, end_index),
        spot_qv=_slice_series(data.spot_qv, from_index, end_index),
        swap_qv=_slice_series(data.swap_qv, from_index, end_index),
        spot_raw_fingerprint=data.spot_raw_fingerprint,
        swap_raw_fingerprint=data.swap_raw_fingerprint,
    )


def _slice_series(series: Series, start: int, end: int) -> Series:
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
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(payload), encoding="utf-8")


def _render_markdown(payload: dict[str, Any]) -> str:
    capacity = payload["capacity"]
    lines = [
        "# SPDP v2 Discovery Results — 2026-08-11",
        "",
        f"- Verdict: `{payload['status']}`",
        f"- Holdout accessed: `{str(payload['holdout_accessed']).lower()}`",
        f"- Continuous episodes: `{capacity['continuous_episodes']}`",
        f"- Segment episodes: `{capacity['segment_episodes']}`",
        "",
        "## Gates",
        "",
    ]
    lines.extend(f"- `{name}`: `{verdict}`" for name, verdict in payload["gates"].items())
    if payload["main"] is not None:
        metrics = payload["main"]["metrics"]
        lines.extend(
            [
                "",
                "## Main",
                "",
                f"- Total return: `{metrics['total_return']:.6f}`",
                f"- Daily Sharpe: `{metrics['sharpe']:.6f}`",
                f"- MaxDD: `{metrics['max_drawdown']:.6f}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Data",
            "",
            f"- Spot SHA-256: `{payload['data']['spot_raw_sha256']}`",
            f"- Swap SHA-256: `{payload['data']['swap_raw_sha256']}`",
            f"- Bars per leg: `{payload['data']['bars_per_leg']}`",
            "- Degenerate bars: "
            f"spot `{payload['data']['spot_degenerate_bars']}`, "
            f"swap `{payload['data']['swap_degenerate_bars']}`",
            "",
            "## Audit metadata",
            "",
            f"- Worktree: `{payload['worktree_status']['lines']}`",
            f"- Tests: `{payload['tests']}`",
            f"- Tool versions: `{payload['tool_versions']}`",
            "- Concentration: `NOT_RUN` (G1 FAIL)",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run frozen SPDP v2 discovery")
    parser.add_argument("--db", default="data/cq.db")
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    args = parser.parse_args()
    try:
        payload = run_discovery(args.db)
    except IntegrityError as exc:
        raise SystemExit(f"SPDP INVALID: {exc}") from exc
    write_outputs(payload, args.json, args.markdown)
    print(json.dumps({"status": payload["status"], "gates": payload["gates"]}, indent=2))


if __name__ == "__main__":
    main()
