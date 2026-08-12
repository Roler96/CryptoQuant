"""Frozen DSPR v1 transfer diagnostic across the other stored USDT swaps."""

from __future__ import annotations

import argparse
import json
import sqlite3
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from cq.context import Series
from cq.core.types import CostModel, MarketSpec, Sizing
from cq.engine.loop import RunResult, run_backtest
from cq.research.downside_recovery import DownsideRecoveryConfig, DownsideRecoveryStrategy
from scripts.research_doge_intraday_open import _engine_metrics, _slice_with_warmup

BAR_MS = 300_000
SOURCE_INSTRUMENT = "DOGE-USDT-SWAP"
DEFAULT_OUTPUT = Path("reports/research/dspr_v1_cross_asset_transfer.json")
MAIN_COSTS = CostModel(fee_bps=10.0, slippage_bps=5.0)


def _instrument_ids(db_path: Path) -> list[str]:
    connection = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            """SELECT DISTINCT inst_id
               FROM ohlcv
               WHERE timeframe='5m' AND inst_id LIKE '%-USDT-SWAP'
               ORDER BY inst_id"""
        ).fetchall()
    finally:
        connection.close()
    return [str(row[0]) for row in rows if row[0] != SOURCE_INSTRUMENT]


def _load_bars(db_path: Path, inst_id: str) -> pd.DataFrame:
    connection = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    try:
        frame = pd.read_sql_query(
            """SELECT ts, open, high, low, close, volume
               FROM ohlcv
               WHERE inst_id=? AND timeframe='5m'
               ORDER BY ts""",
            connection,
            params=[inst_id],
        )
    finally:
        connection.close()
    _validate_frame(frame, inst_id)
    frame.index = pd.to_datetime(frame.pop("ts"), unit="ms", utc=True)
    return frame


def _validate_frame(frame: pd.DataFrame, inst_id: str) -> None:
    if frame.empty:
        raise RuntimeError(f"{inst_id}: 5m query returned no bars")
    timestamps = frame.ts.to_numpy(dtype=np.int64)
    expected_count = (int(timestamps[-1]) - int(timestamps[0])) // BAR_MS + 1
    if expected_count != len(frame) or not bool(np.all(np.diff(timestamps) == BAR_MS)):
        raise RuntimeError(f"{inst_id}: 5m bars are not contiguous")
    numeric = frame.drop(columns="ts").to_numpy(dtype=float)
    if not bool(np.isfinite(numeric).all()):
        raise RuntimeError(f"{inst_id}: input contains non-finite values")
    if bool((frame[["open", "high", "low", "close"]] <= 0.0).any().any()):
        raise RuntimeError(f"{inst_id}: input contains non-positive prices")
    if bool((frame.volume < 0.0).any()):
        raise RuntimeError(f"{inst_id}: input contains negative volume")
    if bool((frame.high < frame[["open", "close"]].max(axis=1)).any()):
        raise RuntimeError(f"{inst_id}: high is below open or close")
    if bool((frame.low > frame[["open", "close"]].min(axis=1)).any()):
        raise RuntimeError(f"{inst_id}: low is above open or close")


def _to_series(frame: pd.DataFrame, inst_id: str) -> Series:
    index = pd.DatetimeIndex(frame.index)
    timestamps_ns = np.asarray(index.asi8, dtype=np.int64)
    return Series(
        inst_id,
        "5m",
        np.floor_divide(timestamps_ns, np.int64(1_000_000)),
        frame.open.to_numpy(dtype=float),
        frame.high.to_numpy(dtype=float),
        frame.low.to_numpy(dtype=float),
        frame.close.to_numpy(dtype=float),
        frame.volume.to_numpy(dtype=float),
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


def _run(series: Series, config: DownsideRecoveryConfig) -> RunResult:
    return run_backtest(
        DownsideRecoveryStrategy(config),
        series,
        MarketSpec(
            series.inst_id,
            "swap",
            lot_size=0.0,
            min_notional=0.0,
            max_leverage=1.0,
            maintenance_margin_rate=0.0,
            contract_size=1.0,
        ),
        costs=MAIN_COSTS,
        sizing=Sizing.ON_ENTRY,
        dust_fraction=0.0,
        evaluation_start_ms=config.evaluation_start_ms,
    )


def _calendar_segments(frame: pd.DataFrame) -> list[tuple[int, datetime, datetime, bool]]:
    index = pd.DatetimeIndex(frame.index)
    timestamps_ns = np.asarray(index.asi8, dtype=np.int64)
    data_start = datetime.fromtimestamp(int(timestamps_ns[0]) / 1_000_000_000, UTC)
    data_end = datetime.fromtimestamp(int(timestamps_ns[-1]) / 1_000_000_000, UTC)
    data_end += timedelta(milliseconds=BAR_MS)
    segments = []
    for year in range(data_start.year, data_end.year + 1):
        calendar_start = datetime(year, 1, 1, tzinfo=UTC)
        calendar_end = datetime(year + 1, 1, 1, tzinfo=UTC)
        start = max(data_start, calendar_start)
        end = min(data_end, calendar_end)
        if start >= end:
            continue
        complete = start == calendar_start and end == calendar_end
        segments.append((year, start, end, complete))
    return segments


def _run_instrument(db_path_text: str, inst_id: str) -> tuple[str, dict]:
    frame = _load_bars(Path(db_path_text), inst_id)
    series = _to_series(frame, inst_id)
    start_ms = int(series.ts[0])
    end_ms = int(series.ts[-1]) + BAR_MS
    config = _config(start_ms, end_ms)
    full = _run(series, config)

    annual = {}
    for year, start, end, complete in _calendar_segments(frame):
        segment_start_ms = int(start.timestamp() * 1_000)
        segment_end_ms = int(end.timestamp() * 1_000)
        segment = _slice_with_warmup(
            series,
            segment_start_ms,
            segment_end_ms,
            config.volatility_window + 2,
        )
        annual[str(year)] = {
            "period_start": start.isoformat(),
            "period_end_exclusive": end.isoformat(),
            "complete_calendar_year": complete,
            **_engine_metrics(
                _run(segment, _config(segment_start_ms, segment_end_ms))
            ),
        }

    index_ns = np.asarray(pd.DatetimeIndex(frame.index).asi8, dtype=np.int64)
    data_start = datetime.fromtimestamp(int(index_ns[0]) / 1_000_000_000, UTC)
    data_end = datetime.fromtimestamp(int(index_ns[-1]) / 1_000_000_000, UTC)
    data_end += timedelta(milliseconds=BAR_MS)
    return inst_id, {
        "data": {
            "start": data_start.isoformat(),
            "end_exclusive": data_end.isoformat(),
            "bars": len(frame),
            "fingerprint": full.manifest.primary_fingerprint,
        },
        "full_period_15bps_per_side": _engine_metrics(full),
        "annual_cold_starts_15bps_per_side": annual,
        "integrity": {
            "engine_version": full.manifest.engine_version,
            "rejections": len(full.rejections),
            "final_flat": full.portfolio.is_flat,
            "fills": len(full.fills),
        },
    }


def run_validation(db_path: Path, workers: int) -> dict:
    instruments = _instrument_ids(db_path)
    results = {}
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_run_instrument, str(db_path), inst_id): inst_id
            for inst_id in instruments
        }
        for future in as_completed(futures):
            inst_id, result = future.result()
            results[inst_id] = result
            print(f"completed {inst_id}", flush=True)

    frozen = asdict(_config(-(2**63), 2**63 - 1))
    frozen.pop("evaluation_start_ms")
    frozen.pop("evaluation_end_ms")
    return {
        "study": "dspr-v1-frozen-cross-asset-transfer",
        "mode": "fixed_DOGE_selected_spec_transfer_diagnostic_not_confirmation",
        "executed_at": datetime.now(UTC).isoformat(),
        "source_instrument": SOURCE_INSTRUMENT,
        "target_instruments": instruments,
        "config": frozen,
        "costs": {
            "fee_bps_per_side": MAIN_COSTS.fee_bps,
            "slippage_bps_per_side": MAIN_COSTS.slippage_bps,
            "funding": "off",
            "sizing": "ON_ENTRY",
        },
        "results": {inst_id: results[inst_id] for inst_id in instruments},
        "disposition": "CROSS_ASSET_TRANSFER_DIAGNOSTIC_NOT_CONFIRMATION",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("data/cq.db"))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.workers <= 0:
        parser.error("--workers must be positive")

    payload = run_validation(args.db, args.workers)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
    print(json.dumps(payload, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
