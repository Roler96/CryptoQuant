#!/usr/bin/env python
"""DLSR run through the existing backtest framework on the fixed explore window."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from cq.context import Series, series_fingerprint
from cq.core.types import CostModel, MarketSpec, Sizing
from cq.engine.funding import NoFunding
from cq.engine.loop import run_backtest
from cq.research.split import FORWARD_FREEZE, to_ms
from cq.strategy.doge_dlsr import BAR_MS, DogeDlsr

DB_PATH = Path("data/cq.db")
INSTRUMENT = "DOGE-USDT"
TIMEFRAME = "5m"
START = "2021-01-01"
END = FORWARD_FREEZE


def load_explore_series() -> Series:
    """Read native 5m bars through a read-only SQLite connection."""
    query = """
        SELECT ts, open, high, low, close, volume
        FROM ohlcv
        WHERE inst_id = ? AND timeframe = ? AND ts >= ? AND ts < ?
        ORDER BY ts
    """
    uri = f"file:{DB_PATH.resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        frame = pd.read_sql_query(
            query,
            connection,
            params=[INSTRUMENT, TIMEFRAME, to_ms(START), to_ms(END)],
        )
    if frame.empty:
        raise RuntimeError("no native DOGE-USDT 5m bars in the fixed explore window")
    return Series(
        inst_id=INSTRUMENT,
        timeframe=TIMEFRAME,
        ts=frame["ts"].to_numpy(dtype=np.int64),
        open=frame["open"].to_numpy(dtype=float),
        high=frame["high"].to_numpy(dtype=float),
        low=frame["low"].to_numpy(dtype=float),
        close=frame["close"].to_numpy(dtype=float),
        volume=frame["volume"].to_numpy(dtype=float),
    )


def validate_explore_series(series: Series) -> None:
    """Seal the protocol's fixed window and exact-next-open preconditions."""
    if series.key != (INSTRUMENT, TIMEFRAME):
        raise ValueError(f"unexpected series {series.key!r}")
    if int(series.ts[0]) != to_ms(START):
        raise ValueError("explore series does not start at the frozen boundary")
    if int(series.ts[-1]) + BAR_MS != to_ms(END):
        raise ValueError("explore series does not end at the forward freeze")
    if not bool(np.all(np.diff(series.ts) == BAR_MS)):
        raise ValueError("DLSR dry-run requires a contiguous native 5m grid")


def main() -> int:
    series = load_explore_series()
    validate_explore_series(series)
    run_backtest(
        strategy=DogeDlsr(),
        primary=series,
        spec=MarketSpec(INSTRUMENT, "spot"),
        initial_cash=10_000.0,
        costs=CostModel(fee_bps=10.0, slippage_bps=5.0),
        funding=NoFunding(),
        sizing=Sizing.ON_ENTRY,
    )
    print("framework dry-run: completed")
    print(f"window: [{START}, {END})")
    print(f"bars: {len(series)}")
    print(f"series fingerprint: {series_fingerprint(series)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
