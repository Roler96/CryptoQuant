"""Shared-engine development validation for DOGE downside recovery."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from cq.context import Series
from cq.core.types import CostModel, MarketSpec, Sizing
from cq.engine.loop import RunResult, run_backtest
from cq.research.downside_recovery import DownsideRecoveryConfig, DownsideRecoveryStrategy
from scripts.research_doge_intraday_frontier import load_bars
from scripts.research_doge_intraday_open import _engine_metrics, _slice_with_warmup

BAR_MS = 300_000
DEFAULT_OUTPUT = Path("reports/research/doge_downside_recovery_development_v1.json")


def _to_series(frame: pd.DataFrame) -> Series:
    return Series(
        "DOGE-USDT-SWAP",
        "5m",
        np.asarray(frame.index.view("int64") // 1_000_000, dtype=np.int64),
        frame.open.to_numpy(dtype=float),
        frame.high.to_numpy(dtype=float),
        frame.low.to_numpy(dtype=float),
        frame.close.to_numpy(dtype=float),
        frame.volume.to_numpy(dtype=float),
    )


def _run(series: Series, config: DownsideRecoveryConfig, costs: CostModel) -> RunResult:
    return run_backtest(
        DownsideRecoveryStrategy(config),
        series,
        MarketSpec(
            "DOGE-USDT-SWAP",
            "swap",
            lot_size=0.0,
            min_notional=0.0,
            max_leverage=1.0,
            maintenance_margin_rate=0.0,
            contract_size=1.0,
        ),
        costs=costs,
        sizing=Sizing.ON_ENTRY,
        dust_fraction=0.0,
        evaluation_start_ms=config.evaluation_start_ms,
    )


def _config(start_ms: int, end_ms: int) -> DownsideRecoveryConfig:
    return DownsideRecoveryConfig(
        shock_window=4,
        volatility_window=7 * 24 * 12,
        shock_z=5.5,
        recovery_floor=0.30,
        recovery_ceiling=0.80,
        hold_bars=12,
        target_weight=0.25,
        evaluation_start_ms=start_ms,
        evaluation_end_ms=end_ms,
    )


def run_validation(db_path: Path) -> dict:
    frame = load_bars(db_path)
    series = _to_series(frame)
    start_ms = int(series.ts[0])
    end_ms = int(series.ts[-1]) + BAR_MS
    config = _config(start_ms, end_ms)

    cost_runs = {}
    raw_results: dict[str, RunResult] = {}
    for per_side_bps in (15.0, 25.0):
        fee = min(10.0, per_side_bps)
        slippage = per_side_bps - fee
        result = _run(series, config, CostModel(fee_bps=fee, slippage_bps=slippage))
        label = f"{per_side_bps:g}bps_per_side"
        raw_results[label] = result
        cost_runs[label] = _engine_metrics(result)

    annual = {}
    for year in sorted(set(frame.index.year)):
        segment_start = pd.Timestamp(f"{year}-01-01T00:00:00Z")
        segment_end = min(
            pd.Timestamp(f"{year + 1}-01-01T00:00:00Z"),
            frame.index[-1] + pd.Timedelta(minutes=5),
        )
        if segment_end <= frame.index[0]:
            continue
        segment_start_ms = max(start_ms, int(segment_start.value // 1_000_000))
        segment_end_ms = int(segment_end.value // 1_000_000)
        segment = _slice_with_warmup(
            series,
            segment_start_ms,
            segment_end_ms,
            config.volatility_window + 2,
        )
        annual[str(year)] = _engine_metrics(
            _run(
                segment,
                _config(segment_start_ms, segment_end_ms),
                CostModel(fee_bps=10.0, slippage_bps=5.0),
            )
        )

    main = raw_results["15bps_per_side"]
    return {
        "study": "doge-downside-shock-recovery-development-v1",
        "mode": "development_validation_on_seen_history_not_confirmation",
        "executed_at": datetime.now(UTC).isoformat(),
        "data": {
            "start": frame.index[0].isoformat(),
            "end_exclusive": (frame.index[-1] + pd.Timedelta(minutes=5)).isoformat(),
            "bars": len(frame),
            "fingerprint": main.manifest.primary_fingerprint,
            "untouched_holdout": False,
        },
        "config": asdict(config),
        "selection_lineage": {
            "stage_1_trials": 120,
            "adaptive_refinement_trials": 420,
            "selection": "all-six-years survivor and local short-hold plateau center",
        },
        "cost_sensitivity": cost_runs,
        "annual_cold_starts_15bps_per_side": annual,
        "integrity": {
            "engine_version": main.manifest.engine_version,
            "rejections": len(main.rejections),
            "final_flat": main.portfolio.is_flat,
            "fills": len(main.fills),
        },
        "funding": "off; historical funding does not cover the full study",
        "disposition": (
            "DEVELOPMENT_SURVIVOR_AWAITING_FORWARD_CONFIRMATION"
            if all(metrics["return"] > 0.0 for metrics in annual.values())
            else "DEVELOPMENT_FAIL"
        ),
    }


def main() -> None:
    payload = run_validation(Path("data/cq.db"))
    DEFAULT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_OUTPUT.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
    print(json.dumps(payload, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
