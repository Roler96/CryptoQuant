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
    # False when the walk stopped at the page cap rather than at `start_ms` or
    # at the end of the exchange's history.
    complete: bool = True


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
    already holds.

    Each page is written as it arrives rather than accumulated and flushed at
    the end. A full history is ~500 pages per instrument, and buffering all of
    it means an interruption at page 499 stores nothing and resumes from
    nowhere — the opposite of the "resumable" property this is supposed to
    have.

    Completion is recorded separately from the rows, because the rows cannot
    express it: a walk cut short after two pages leaves a store that looks
    identical to one for an instrument listed two pages ago. See
    `incremental_start`.
    """
    bar = okx_bar(timeframe)
    cursor = end_ms
    pages = 0
    skipped_unclosed = 0
    seen = 0
    new = 0
    oldest_ts: int | None = None
    newest_ts: int | None = None
    complete = False

    # Read before the walk marks itself in progress: a top-up requests only
    # the last bar onwards, and the span it extends is the one recorded by
    # whichever walk completed before it.
    previous = store.ohlcv_sync_state(inst_id, timeframe)
    store.begin_ohlcv_sync(inst_id, timeframe, start_ms)

    while pages < max_pages:
        page = client.history_candles(inst_id, bar=bar, before_ts=cursor, limit=PAGE_SIZE)
        pages += 1
        if not page:
            # The exchange has nothing older: history is exhausted, which is a
            # complete walk even though `start_ms` was never reached.
            complete = True
            break

        rows: list[tuple] = []
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

        if rows:
            written = store.upsert_ohlcv(rows)
            seen += written.seen
            new += written.new
            page_timestamps = [row[2] for row in rows]
            page_oldest, page_newest = min(page_timestamps), max(page_timestamps)
            oldest_ts = page_oldest if oldest_ts is None else min(oldest_ts, page_oldest)
            newest_ts = page_newest if newest_ts is None else max(newest_ts, page_newest)

        # Advance from the raw page, not from the kept rows: dropping the
        # unclosed candle must not stall the cursor.
        oldest_in_page = int(page[-1][_TS])
        if oldest_in_page < start_ms:
            complete = True
            break
        cursor = oldest_in_page
        # Deliberately no "short page means end of history" shortcut: that
        # assumes the server always fills a page, and a server returning fewer
        # rows than asked would silently truncate the backfill. Terminating
        # only on an empty page or on reaching start_ms costs one request.

    if complete:
        _, _, stored_newest = store.ohlcv_coverage(inst_id, timeframe)
        covered_from = start_ms
        covered_to = max(filter(None, (newest_ts, stored_newest, end_ms)), default=start_ms)
        # A walk starting inside an already-covered span extends it. Without
        # this the nightly top-up would shrink the record of a full history
        # down to its own one-bar request, and the next run would conclude
        # nothing had ever been walked.
        if previous is not None and previous.complete and previous.covered_to >= start_ms:
            covered_from = min(covered_from, previous.covered_from)
            covered_to = max(covered_to, previous.covered_to)
        store.finish_ohlcv_sync(inst_id, timeframe, covered_from, int(covered_to), start_ms)

    result = SyncResult(
        inst_id=inst_id,
        timeframe=timeframe,
        result=WriteResult(seen=seen, new=new),
        pages=pages,
        skipped_unclosed=skipped_unclosed,
        oldest_ts=oldest_ts,
        newest_ts=newest_ts,
        complete=complete,
    )
    logger.info(
        "{} {}: {} new / {} seen over {} pages ({} unclosed dropped)",
        inst_id,
        timeframe,
        new,
        seen,
        pages,
        skipped_unclosed,
    )
    if pages >= max_pages:
        logger.warning("{} hit the {}-page cap; range may be incomplete", inst_id, max_pages)
    return result


def incremental_start(store: Store, inst_id: str, timeframe: str, default_start_ms: int) -> int:
    """Where a routine re-sync should begin.

    Resumes one bar before the newest stored bar — so a tail written mid-page
    is re-read rather than trusted — but *only* when a previous walk is known
    to have covered everything back to `default_start_ms`.

    Otherwise it starts over from `default_start_ms`. OKX pages from newest to
    oldest, so an interrupted backfill leaves the newest bars stored and the
    older ones missing; resuming at the newest bar would fetch a handful of
    fresh candles, declare success, and leave the hole in place permanently.
    The stored rows cannot distinguish that from an instrument listed
    recently, which is why completion is recorded rather than inferred.
    """
    count, _, newest = store.ohlcv_coverage(inst_id, timeframe)
    if not count or newest is None:
        return default_start_ms

    state = store.ohlcv_sync_state(inst_id, timeframe)
    if state is None or not state.complete or state.covered_from > default_start_ms:
        logger.info(
            "{} {}: no completed walk covering {} — restarting the backfill there",
            inst_id,
            timeframe,
            default_start_ms,
        )
        return default_start_ms
    return newest - duration_ms(timeframe)
