"""One-shot temporal challenge for frozen DOGE CPER."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from cq.core.types import CostModel
from cq.research.coherent_path import CoherentPathConfig
from scripts.research_doge_intraday_open import (
    _engine_metrics,
    _run_engine,
    _to_series,
    resample_15m,
)

CHALLENGE_START = "2025-06-01T00:00:00Z"
CHALLENGE_END = "2026-08-03T06:45:00Z"
START_MS = int(pd.Timestamp(CHALLENGE_START).value // 1_000_000)
END_MS = int(pd.Timestamp(CHALLENGE_END).value // 1_000_000)
WARMUP_MS = 19 * 15 * 60 * 1000
PROTOCOL = (
    "docs/research/doge-intraday/"
    "COHERENT_PATH_EXHAUSTION_CHALLENGE_PROTOCOL_2026-08-11.md"
)
DEFAULT_OUTPUT = Path("reports/research/doge_cper_temporal_challenge_2026-08-11.json")


def load_challenge(db_path: Path) -> pd.DataFrame:
    connection = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    try:
        frame = pd.read_sql_query(
            """SELECT ts, open, high, low, close, volume, quote_volume
               FROM ohlcv
               WHERE inst_id='DOGE-USDT-SWAP' AND timeframe='5m'
                 AND ts>=? AND ts<? ORDER BY ts""",
            connection,
            params=[START_MS - WARMUP_MS, END_MS],
        )
    finally:
        connection.close()
    if frame.empty:
        raise RuntimeError("challenge query returned no bars")
    expected = np.arange(frame.ts.iloc[0], frame.ts.iloc[-1] + 300_000, 300_000)
    if len(expected) != len(frame) or not np.array_equal(expected, frame.ts.to_numpy()):
        raise RuntimeError("challenge native 5m bars are not contiguous")
    numeric = frame.drop(columns="ts").to_numpy(dtype=float)
    if not np.isfinite(numeric).all():
        raise RuntimeError("challenge contains non-finite OHLCV")
    if (frame[["open", "high", "low", "close"]] <= 0.0).any().any():
        raise RuntimeError("challenge contains non-positive prices")
    if (frame[["volume", "quote_volume"]] < 0.0).any().any():
        raise RuntimeError("challenge contains negative volume")
    frame.index = pd.to_datetime(frame.pop("ts"), unit="ms", utc=True)
    return frame


def run_challenge(db_path: Path) -> dict:
    native = load_challenge(db_path)
    bars = resample_15m(native)
    series = _to_series(bars)
    config = CoherentPathConfig(
        window_bars=18,
        efficiency_threshold=0.78,
        hold_bars=12,
        target_weight=0.25,
        evaluation_start_ms=START_MS,
        evaluation_end_ms=END_MS,
    )
    payload = {
        "study": "doge-cper-temporal-challenge-v1",
        "protocol": PROTOCOL,
        "executed_at": datetime.now(UTC).isoformat(),
        "challenge_accessed": True,
        "data": {
            "start": CHALLENGE_START,
            "end_exclusive": CHALLENGE_END,
            "native_bars_including_warmup": len(native),
            "bars_15m_including_warmup": len(bars),
        },
        "config": asdict(config),
        "funding": "off; measured funding does not cover challenge start",
        "gates": {
            "H0_integrity": "NOT_RUN",
            "H1_capacity": "NOT_RUN",
            "H2_main_economics": "NOT_RUN",
            "H3_directional_mechanism": "NOT_RUN",
            "H4_concentration": "NOT_RUN",
            "H5_cost_stress": "NOT_RUN",
        },
        "main": None,
        "stress": None,
    }
    try:
        main_result = _run_engine(
            series,
            config,
            CostModel(fee_bps=10.0, slippage_bps=5.0),
        )
        main = _engine_metrics(main_result)
    except Exception as exc:  # noqa: BLE001 - challenge must serialize INVALID
        payload["status"] = "INVALID"
        payload["gates"]["H0_integrity"] = "FAIL"
        payload["error"] = f"{type(exc).__name__}: {exc}"
        return payload

    payload["main"] = main
    payload["integrity"] = {
        "primary_fingerprint": main_result.manifest.primary_fingerprint,
        "engine_version": main_result.manifest.engine_version,
        "rejections": len(main_result.rejections),
        "final_flat": main_result.portfolio.is_flat,
        "fills": len(main_result.fills),
    }
    payload["gates"]["H0_integrity"] = "PASS"
    h1 = main["episodes"] >= 20
    payload["gates"]["H1_capacity"] = "PASS" if h1 else "FAIL"
    if not h1:
        payload["status"] = "TEMPORAL_CHALLENGE_FAIL"
        return payload

    h2 = main["return"] > 0.0 and main["sharpe"] >= 0.50 and main["max_drawdown"] >= -0.20
    payload["gates"]["H2_main_economics"] = "PASS" if h2 else "FAIL"
    if not h2:
        payload["status"] = "TEMPORAL_CHALLENGE_FAIL"
        return payload

    h3 = main["long_pnl"] > 0.0 and main["short_pnl"] > 0.0
    payload["gates"]["H3_directional_mechanism"] = "PASS" if h3 else "FAIL"
    h4 = main["best_5_positive_pnl_share"] < 0.60
    payload["gates"]["H4_concentration"] = "PASS" if h4 else "FAIL"
    if not h3 or not h4:
        payload["status"] = "TEMPORAL_CHALLENGE_FAIL"
        return payload

    try:
        stress_result = _run_engine(
            series,
            config,
            CostModel(fee_bps=15.0, slippage_bps=10.0),
        )
        stress = _engine_metrics(stress_result)
    except Exception as exc:  # noqa: BLE001
        payload["status"] = "INVALID"
        payload["gates"]["H5_cost_stress"] = "FAIL"
        payload["error"] = f"{type(exc).__name__}: {exc}"
        return payload
    payload["stress"] = stress
    h5 = stress["return"] > 0.0 and stress["sharpe"] >= 0.25 and stress["max_drawdown"] >= -0.20
    payload["gates"]["H5_cost_stress"] = "PASS" if h5 else "FAIL"
    payload["status"] = (
        "TEMPORAL_CHALLENGE_PASS" if h5 else "TEMPORAL_CHALLENGE_FAIL"
    )
    return payload


def main() -> None:
    report = run_challenge(Path("data/cq.db"))
    DEFAULT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_OUTPUT.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
