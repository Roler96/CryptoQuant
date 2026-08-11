"""Shared-engine validation for the PIRD downside-residual candidate."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from cq.context import Series
from cq.core.types import CostModel, MarketSpec, Sizing
from cq.engine.loop import RunResult, run_backtest
from cq.research.propagator_residual import (
    ResidualDecisionReplayStrategy,
    ResidualReplayConfig,
    propagator_features,
)
from scripts.research_doge_intraday_frontier import load_bars
from scripts.research_doge_intraday_open import _engine_metrics
from scripts.research_doge_pird import _base_features, _daily_frozen_models, _signal

BAR_MS = 300_000
OUTPUT = Path("reports/research/doge_pird_downside_residual_validation.json")


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


def _raw_decision_times(frame: pd.DataFrame) -> frozenset[int]:
    base = _base_features(frame)
    _state, change = propagator_features(base["flow"], base["valid"], tau=12)
    alpha, beta, sigma = _daily_frozen_models(
        pd.DatetimeIndex(frame.index),
        change,
        base["returns"],
        4032,
    )
    raw = _signal(
        base["returns"],
        change,
        base["activity"],
        alpha,
        beta,
        sigma,
        9.0,
    )
    selected = np.flatnonzero(raw > 0.0)
    timestamps = np.asarray(frame.index.view("int64") // 1_000_000, dtype=np.int64)
    return frozenset(int(value) for value in timestamps[selected])


def _run(
    series: Series,
    decision_times: frozenset[int],
    *,
    per_side_bps: float,
    evaluation_end_ms: int,
) -> RunResult:
    return run_backtest(
        ResidualDecisionReplayStrategy(
            decision_times,
            ResidualReplayConfig(
                hold_bars=12,
                target_weight=0.25,
                evaluation_end_ms=evaluation_end_ms,
            ),
        ),
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
        costs=CostModel(
            fee_bps=min(10.0, per_side_bps),
            slippage_bps=per_side_bps - min(10.0, per_side_bps),
        ),
        sizing=Sizing.ON_ENTRY,
        dust_fraction=0.0,
    )


def run_validation(db_path: Path) -> dict:
    frame = load_bars(db_path)
    full_series = _to_series(frame)
    decisions = _raw_decision_times(frame)
    end_ms = int(full_series.ts[-1]) + BAR_MS
    main = _run(
        full_series,
        decisions,
        per_side_bps=15.0,
        evaluation_end_ms=end_ms,
    )
    filled = [record for record in main.transactions if record.status == "filled"]
    episode_pnls = np.asarray(
        [
            filled[index + 1].equity_after - filled[index].equity_before
            for index in range(0, len(filled), 2)
        ],
        dtype=float,
    )
    positive = np.sort(episode_pnls[episode_pnls > 0.0])[::-1]
    top5 = float(positive[:5].sum() / positive.sum()) if len(positive) else 0.0
    return {
        "study": "doge-pird-downside-residual-development-validation",
        "mode": "shared_engine_replay_of_causally_precomputed_decisions",
        "executed_at": datetime.now(UTC).isoformat(),
        "candidate": {
            "side": "long_only",
            "regression_window": 4032,
            "tau_half_life_bars": 12,
            "z_resid": 9.0,
            "hold_bars": 12,
            "target_weight": 0.25,
        },
        "data": {
            "start": frame.index[0].isoformat(),
            "end_exclusive": (frame.index[-1] + pd.Timedelta(minutes=5)).isoformat(),
            "bars": len(frame),
            "fingerprint": main.manifest.primary_fingerprint,
            "untouched_holdout": False,
        },
        "shared_engine_15bps_per_side": _engine_metrics(main),
        "other_costs_and_annual_slices": (
            "validated in the vectorized development ledger; shared-engine replay "
            "is intentionally limited to the main run because four full replays "
            "benchmark at more than 15 minutes"
        ),
        "concentration": {"top5_positive_episode_pnl": top5},
        "integrity": {
            "engine_version": main.manifest.engine_version,
            "raw_decision_timestamps": len(decisions),
            "fills": len(main.fills),
            "rejections": len(main.rejections),
            "final_flat": main.portfolio.is_flat,
            "decision_source": (
                "causal vectorized PIRD features; replay strategy validates shared "
                "next-open execution, costs, sizing, hold and account semantics"
            ),
        },
        "disposition": "DEVELOPMENT_SURVIVOR_REQUIRES_FORWARD_CONFIRMATION",
    }


def main() -> None:
    report = run_validation(Path("data/cq.db"))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
