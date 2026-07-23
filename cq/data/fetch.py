"""OHLCV backfill from OKX.

Only closed candles are ever stored. OKX returns the in-progress candle from
both `/market/candles` and `/market/history-candles`, flagged `confirm=0`;
storing one would let a strategy read a bar whose high, low and close are
still moving — the repainting defect that made the previous system's live
signals disagree with its backtests.
"""

from __future__ import annotations

import queue
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from loguru import logger

from cq.core.clock import BASE_TIMEFRAME, duration_ms, floor_to_bar, okx_bar
from cq.data.protocols import CandleSource
from cq.data.store import Store, SyncState, WriteResult

PAGE_SIZE = 100

# Index of each field in an OKX candle row.
_TS, _OPEN, _HIGH, _LOW, _CLOSE, _VOL, _VOL_CCY, _VOL_QUOTE, _CONFIRM = range(9)

CONFIRM_CLOSED = "1"

# A page callback receives one page's worth of storable rows.
PageSink = Callable[[list[tuple]], None]


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


@dataclass
class WalkSummary:
    """What one bounded newest-to-oldest page walk observed.

    Row counts live in `SyncResult`, not here: a walk emits rows to whatever
    sink is given and never learns how many were new, so counting belongs to
    whoever owns the store.
    """

    pages: int
    skipped_unclosed: int
    oldest_ts: int | None
    newest_ts: int | None
    # False only when the walk stopped at the page cap — i.e. its window was
    # not fully covered.
    complete: bool


def _walk_window(
    client: CandleSource,
    inst_id: str,
    timeframe: str,
    bar: str,
    lo_ms: int,
    hi_ms: int | None,
    emit: PageSink,
    *,
    max_pages: int,
) -> WalkSummary:
    """Page closed candles in [lo_ms, hi_ms) from newest to oldest.

    `hi_ms` is exclusive; `None` means "from the exchange's most recent bar".
    Each page is handed to `emit` as it arrives rather than buffered, so a walk
    that dies partway leaves the pages it already reached wherever `emit` put
    them.

    The upper bound is enforced by both the cursor and a row filter: partitioned
    windows share edges, and the filter keeps a page that straddles a boundary
    from being counted by both sides.
    """
    cursor = hi_ms
    pages = 0
    skipped_unclosed = 0
    oldest_ts: int | None = None
    newest_ts: int | None = None
    complete = False

    while pages < max_pages:
        page = client.history_candles(inst_id, bar=bar, before_ts=cursor, limit=PAGE_SIZE)
        pages += 1
        if not page:
            # The exchange has nothing older: history is exhausted, which is a
            # complete walk even though `lo_ms` was never reached.
            complete = True
            break

        rows: list[tuple] = []
        for entry in page:
            ts = int(entry[_TS])
            if ts < lo_ms:
                continue
            if hi_ms is not None and ts >= hi_ms:
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
            emit(rows)
            page_timestamps = [row[2] for row in rows]
            page_oldest, page_newest = min(page_timestamps), max(page_timestamps)
            oldest_ts = page_oldest if oldest_ts is None else min(oldest_ts, page_oldest)
            newest_ts = page_newest if newest_ts is None else max(newest_ts, page_newest)

        # Advance from the raw page, not from the kept rows: dropping the
        # unclosed candle must not stall the cursor.
        oldest_in_page = int(page[-1][_TS])
        if oldest_in_page < lo_ms:
            complete = True
            break
        cursor = oldest_in_page
        # Deliberately no "short page means end of history" shortcut: that
        # assumes the server always fills a page, and a server returning fewer
        # rows than asked would silently truncate the backfill. Terminating
        # only on an empty page or on reaching lo_ms costs one request.

    return WalkSummary(
        pages=pages,
        skipped_unclosed=skipped_unclosed,
        oldest_ts=oldest_ts,
        newest_ts=newest_ts,
        complete=complete,
    )


def _record_completion(
    store: Store,
    inst_id: str,
    timeframe: str,
    start_ms: int,
    end_ms: int | None,
    newest_ts: int | None,
    previous: SyncState | None,
) -> None:
    """Write the covered span of a walk that finished without a hole.

    A walk starting inside an already-covered span extends it. Without this the
    nightly top-up would shrink the record of a full history down to its own
    one-bar request, and the next run would conclude nothing had ever been
    walked.
    """
    _, _, stored_newest = store.ohlcv_coverage(inst_id, timeframe)
    covered_from = start_ms
    covered_to = max(filter(None, (newest_ts, stored_newest, end_ms)), default=start_ms)
    if previous is not None and previous.complete and previous.covered_to >= start_ms:
        covered_from = min(covered_from, previous.covered_from)
        covered_to = max(covered_to, previous.covered_to)
    store.finish_ohlcv_sync(inst_id, timeframe, covered_from, int(covered_to), start_ms)


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
    seen = 0
    new = 0

    def emit(rows: list[tuple]) -> None:
        nonlocal seen, new
        written = store.upsert_ohlcv(rows)
        seen += written.seen
        new += written.new

    # Read before the walk marks itself in progress: a top-up requests only
    # the last bar onwards, and the span it extends is the one recorded by
    # whichever walk completed before it.
    previous = store.ohlcv_sync_state(inst_id, timeframe)
    store.begin_ohlcv_sync(inst_id, timeframe, start_ms)

    summary = _walk_window(
        client, inst_id, timeframe, bar, start_ms, end_ms, emit, max_pages=max_pages
    )

    if summary.complete:
        _record_completion(
            store, inst_id, timeframe, start_ms, end_ms, summary.newest_ts, previous
        )

    result = SyncResult(
        inst_id=inst_id,
        timeframe=timeframe,
        result=WriteResult(seen=seen, new=new),
        pages=summary.pages,
        skipped_unclosed=summary.skipped_unclosed,
        oldest_ts=summary.oldest_ts,
        newest_ts=summary.newest_ts,
        complete=summary.complete,
    )
    logger.info(
        "{} {}: {} new / {} seen over {} pages ({} unclosed dropped)",
        inst_id,
        timeframe,
        new,
        seen,
        summary.pages,
        summary.skipped_unclosed,
    )
    if summary.pages >= max_pages:
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


# ---- concurrent backfill ----------------------------------------------------
#
# One instrument's history is thousands of pages walked strictly oldest-first,
# and each page is a round trip dominated by network latency, not by the
# exchange's rate limit — so the wire sits idle between requests. Splitting the
# range into contiguous time windows lets several walks run at once and keeps
# the wire busy. The exchange pages backwards from a cursor, so any window can
# be walked in isolation: give it its own upper edge and it never needs a
# neighbour's result.

# Target pages per window. Small enough that even a modest range yields several
# windows — a 44-page range splits into five, so a worker pool of eight is
# nearly filled by one instrument alone — yet not so small that adjacent windows
# refetch a wasteful share of boundary bars. Expressed in pages so it tracks
# `PAGE_SIZE`. Below one window's worth (a near-empty top-up) the range is left
# whole: splitting it would only spend round trips discovering emptiness.
_PAGES_PER_WINDOW = 8

# A hard cap on window count. For an ordinary history the pages-per-window
# target sets the count well below this; the cap only bites on a very deep
# fine-grained backfill, keeping each in-flight window's buffered rows bounded.
_MAX_WINDOWS_PER_INSTRUMENT = 128


@dataclass
class SyncJob:
    """One instrument to backfill and where its walk should begin."""

    inst_id: str
    start_ms: int


def _partition_windows(
    start_ms: int, upper_ms: int, step_ms: int, *, open_ended: bool
) -> list[tuple[int, int | None]]:
    """Split [start_ms, upper_ms) into contiguous, bar-aligned windows.

    Edges meet exactly — window i ends where window i-1 begins — so a boundary
    bar lands in precisely one window.

    When `open_ended`, `upper_ms` is only a clock reading standing in for "now",
    so the newest window carries `None` as its upper edge and walks from the
    exchange's most recent bar — a bar that closes mid-run is still picked up.
    When a real `--end` was given, `open_ended` is False and every window,
    including the newest, keeps its hard edge so nothing past the cap is stored.
    """
    if upper_ms <= start_ms:
        return [(start_ms, upper_ms if not open_ended else None)]

    total_bars = (upper_ms - start_ms + step_ms - 1) // step_ms
    total_pages = max(1, (total_bars + PAGE_SIZE - 1) // PAGE_SIZE)
    windows = min(
        _MAX_WINDOWS_PER_INSTRUMENT, max(1, total_pages // _PAGES_PER_WINDOW)
    )
    if windows <= 1:
        return [(start_ms, None if open_ended else upper_ms)]

    chunk_bars = (total_bars + windows - 1) // windows
    edges: list[tuple[int, int | None]] = []
    lo = start_ms
    while lo < upper_ms:
        hi = min(upper_ms, lo + chunk_bars * step_ms)
        edges.append((lo, hi))
        lo = hi
    if open_ended:
        last_lo, _ = edges[-1]
        edges[-1] = (last_lo, None)
    return edges


@dataclass
class _InstrumentProgress:
    """Rolls a concurrent instrument's window results back into one outcome."""

    start_ms: int
    previous: SyncState | None
    remaining: int
    complete: bool = True
    seen: int = 0
    new: int = 0
    pages: int = 0
    skipped: int = 0
    oldest: int | None = None
    newest: int | None = None


def sync_ohlcv_concurrent(
    client_factory: Callable[[], CandleSource],
    store: Store,
    jobs: Sequence[SyncJob],
    *,
    now_ms: int,
    end_ms: int | None = None,
    timeframe: str = BASE_TIMEFRAME,
    concurrency: int = 8,
    max_pages: int = 10_000,
) -> tuple[list[SyncResult], dict[str, str]]:
    """Backfill several instruments at once, fetching in parallel.

    Every worker owns one client from `client_factory`; the store is touched
    only from this thread, so its single-connection contract holds. Workers
    fetch and buffer a window, and this thread upserts each returned buffer as
    the window lands — the network is the bottleneck, so a lone writer keeps up.

    Returns the per-instrument outcomes and a map of instrument to error for any
    whose windows failed. A failed instrument is left un-finished, so a later
    run restarts its walk rather than trusting a partial one.
    """
    bar = okx_bar(timeframe)
    step = duration_ms(timeframe)
    default_upper = floor_to_bar(now_ms, timeframe)

    # Build every (instrument, window) task, and open each instrument's walk.
    # `previous` is read before `begin` marks the walk in progress, exactly as
    # the sequential path does, so a top-up still extends the completed span.
    tasks: list[tuple[str, int, int | None]] = []
    progress: dict[str, _InstrumentProgress] = {}
    for job in jobs:
        upper = end_ms if end_ms is not None else default_upper
        windows = _partition_windows(
            job.start_ms, upper, step, open_ended=end_ms is None
        )
        previous = store.ohlcv_sync_state(job.inst_id, timeframe)
        store.begin_ohlcv_sync(job.inst_id, timeframe, job.start_ms)
        progress[job.inst_id] = _InstrumentProgress(
            start_ms=job.start_ms, previous=previous, remaining=len(windows)
        )
        for lo, hi in windows:
            tasks.append((job.inst_id, lo, hi))

    errors: dict[str, str] = {}
    if not tasks:
        return [], errors

    workers = max(1, min(concurrency, len(tasks)))
    clients: queue.Queue[CandleSource] = queue.Queue()
    for _ in range(workers):
        clients.put(client_factory())

    def run_window(task: tuple[str, int, int | None]) -> tuple[str, WalkSummary, list[tuple]]:
        inst_id, lo, hi = task
        client = clients.get()
        try:
            buffer: list[tuple] = []
            summary = _walk_window(
                client, inst_id, timeframe, bar, lo, hi, buffer.extend, max_pages=max_pages
            )
            return inst_id, summary, buffer
        finally:
            clients.put(client)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_window, task): task for task in tasks}
        for future in as_completed(futures):
            inst_id = futures[future][0]
            state = progress[inst_id]
            state.remaining -= 1
            try:
                _inst, summary, buffer = future.result()
            except Exception as exc:  # noqa: BLE001 - reported per instrument
                errors[inst_id] = f"{type(exc).__name__}: {exc}"
                state.complete = False
                continue
            written = store.upsert_ohlcv(buffer)  # main-thread write
            state.seen += written.seen
            state.new += written.new
            state.pages += summary.pages
            state.skipped += summary.skipped_unclosed
            if summary.oldest_ts is not None:
                state.oldest = _merge_min(state.oldest, summary.oldest_ts)
            if summary.newest_ts is not None:
                state.newest = _merge_max(state.newest, summary.newest_ts)
            if not summary.complete:
                state.complete = False

    results: list[SyncResult] = []
    for inst_id, state in progress.items():
        done = inst_id not in errors and state.complete
        if done:
            _record_completion(
                store, inst_id, timeframe, state.start_ms, end_ms, state.newest, state.previous
            )
        results.append(
            SyncResult(
                inst_id=inst_id,
                timeframe=timeframe,
                result=WriteResult(seen=state.seen, new=state.new),
                pages=state.pages,
                skipped_unclosed=state.skipped,
                oldest_ts=state.oldest,
                newest_ts=state.newest,
                complete=done,
            )
        )
    return results, errors


def _merge_min(current: int | None, value: int) -> int:
    return value if current is None else min(current, value)


def _merge_max(current: int | None, value: int) -> int:
    return value if current is None else max(current, value)
