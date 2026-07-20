"""OHLCV backfill from OKX.

Only closed candles are ever stored. OKX returns the in-progress candle from
both `/market/candles` and `/market/history-candles`, flagged `confirm=0`;
storing one would let a strategy read a bar whose high, low and close are
still moving — the repainting defect that made the previous system's live
signals disagree with its backtests.
"""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from cq.core.clock import BASE_TIMEFRAME, duration_ms, okx_bar
from cq.data.protocols import CandleSource
from cq.data.store import Store, WriteResult

PAGE_SIZE = 100

# Index of each field in an OKX candle row.
_TS, _OPEN, _HIGH, _LOW, _CLOSE, _VOL, _VOL_CCY, _VOL_QUOTE, _CONFIRM = range(9)

CONFIRM_CLOSED = "1"


@dataclass
class SyncResult:
    """Outcome of one instrument's backfill."""

    inst_id: str
    timeframe: str
    result: WriteResult
    pages: int
    skipped_unclosed: int
    oldest_ts: int | None
    newest_ts: int | None


def sync_ohlcv(
    client: CandleSource,
    store: Store,
    inst_id: str,
    start_ms: int,
    end_ms: int | None = None,
    timeframe: str = BASE_TIMEFRAME,
    max_pages: int = 10_000,
) -> SyncResult:
    """Backfill closed candles for `inst_id` covering [start_ms, end_ms).

    OKX only pages backwards, so this walks from the newest bar towards
    `start_ms`. Overlapping re-fetches are harmless: storage ignores rows it
    already holds, which also makes an interrupted sync resumable.
    """
    bar = okx_bar(timeframe)
    cursor = end_ms
    rows: list[tuple] = []
    pages = 0
    skipped_unclosed = 0

    while pages < max_pages:
        page = client.history_candles(inst_id, bar=bar, before_ts=cursor, limit=PAGE_SIZE)
        pages += 1
        if not page:
            break

        for entry in page:
            ts = int(entry[_TS])
            if ts < start_ms:
                continue
            if entry[_CONFIRM] != CONFIRM_CLOSED:
                skipped_unclosed += 1
                continue
            rows.append(
                (
                    inst_id,
                    timeframe,
                    ts,
                    float(entry[_OPEN]),
                    float(entry[_HIGH]),
                    float(entry[_LOW]),
                    float(entry[_CLOSE]),
                    float(entry[_VOL]),
                    float(entry[_VOL_QUOTE]),
                )
            )

        # Advance from the raw page, not from the kept rows: dropping the
        # unclosed candle must not stall the cursor.
        oldest_in_page = int(page[-1][_TS])
        if oldest_in_page < start_ms:
            break
        cursor = oldest_in_page
        # Deliberately no "short page means end of history" shortcut: that
        # assumes the server always fills a page, and a server returning fewer
        # rows than asked would silently truncate the backfill. Terminating
        # only on an empty page or on reaching start_ms costs one request.

    written = store.upsert_ohlcv(rows)
    timestamps = [r[2] for r in rows]
    result = SyncResult(
        inst_id=inst_id,
        timeframe=timeframe,
        result=written,
        pages=pages,
        skipped_unclosed=skipped_unclosed,
        oldest_ts=min(timestamps) if timestamps else None,
        newest_ts=max(timestamps) if timestamps else None,
    )
    logger.info(
        "{} {}: {} new / {} seen over {} pages ({} unclosed dropped)",
        inst_id,
        timeframe,
        written.new,
        written.seen,
        pages,
        skipped_unclosed,
    )
    if pages >= max_pages:
        logger.warning("{} hit the {}-page cap; range may be incomplete", inst_id, max_pages)
    return result


def incremental_start(store: Store, inst_id: str, timeframe: str, default_start_ms: int) -> int:
    """Where a routine re-sync should begin.

    Resumes one bar before the newest stored bar so a partially written tail
    is re-fetched rather than trusted.
    """
    count, _, newest = store.ohlcv_coverage(inst_id, timeframe)
    if not count or newest is None:
        return default_start_ms
    return newest - duration_ms(timeframe)
