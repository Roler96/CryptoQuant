"""OHLCV backfill: closed-bar filtering, paging and resumption."""

import threading

import pytest

from cq.core.clock import HOUR_MS
from cq.data.fetch import (
    SyncJob,
    incremental_start,
    sync_ohlcv,
    sync_ohlcv_concurrent,
)
from cq.data.store import Store

START = 1_700_000_000_000 - (1_700_000_000_000 % HOUR_MS)


def candle(ts, close=1.0, confirm="1"):
    """An OKX candle row: [ts, o, h, l, c, vol, volCcy, volQuote, confirm]."""
    return [str(ts), "1.0", "2.0", "0.5", str(close), "10", "10", "20", confirm]


class FakeCandles:
    """Serves pages newest-first, honouring the `before_ts` cursor like OKX."""

    def __init__(self, rows: list[list[str]], page_size: int = 100):
        # rows: list of candle rows in any order; served newest first.
        self.rows = sorted(rows, key=lambda r: int(r[0]), reverse=True)
        self.page_size = page_size
        self.calls = []

    def milliseconds(self):
        return START + 1_000_000

    def history_candles(self, inst_id, bar="1H", before_ts=None, limit=100):
        self.calls.append((inst_id, bar, before_ts))
        available = self.rows
        if before_ts is not None:
            available = [r for r in available if int(r[0]) < before_ts]
        return available[: min(limit, self.page_size)]


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "test.db") as s:
        yield s


def test_unclosed_candle_is_never_stored(store):
    # OKX returns the in-progress candle from history-candles with confirm=0.
    # Storing it is the repainting defect: its high/low/close still move.
    client = FakeCandles(
        [
            candle(START, close=1.0),
            candle(START + HOUR_MS, close=2.0),
            candle(START + 2 * HOUR_MS, close=3.0, confirm="0"),
        ]
    )

    outcome = sync_ohlcv(client, store, "DOGE-USDT-SWAP", start_ms=START)

    assert outcome.skipped_unclosed == 1
    assert outcome.result.new == 2
    frame = store.load_ohlcv("DOGE-USDT-SWAP", "1h")
    assert len(frame) == 2
    assert outcome.newest_ts == START + HOUR_MS


def test_cursor_advances_by_raw_page_not_by_kept_rows(store):
    # Paging must key off what the exchange returned, not off what survived
    # filtering, or a page could be re-requested forever. Pinned as an exact
    # cursor sequence: the oldest raw timestamp of each preceding page.
    rows = [candle(START + i * HOUR_MS) for i in range(5)]
    rows.append(candle(START + 5 * HOUR_MS, confirm="0"))
    client = FakeCandles(rows, page_size=2)

    outcome = sync_ohlcv(client, store, "DOGE-USDT-SWAP", start_ms=START, max_pages=10)

    assert outcome.result.new == 5
    cursors = [call[2] for call in client.calls]
    # Pages served newest-first in twos: [5u,4], [3,2], [1,0], then one empty
    # page to terminate — the cost of not trusting a short page to mean "end".
    assert cursors == [
        None,
        START + 4 * HOUR_MS,
        START + 2 * HOUR_MS,
        START,
    ]
    assert len(cursors) == len(set(cursors)), "cursor repeated: paging stalled"


def test_cursor_survives_an_unclosed_bar_at_the_end_of_a_page(store):
    # Defensive: a mid-history unclosed bar is an anomaly, but if the cursor
    # were taken from the surviving rows it would re-request the same window.
    rows = [candle(START + i * HOUR_MS) for i in range(1, 6)]
    rows.append(candle(START, confirm="0"))  # oldest bar, and unclosed
    client = FakeCandles(rows, page_size=2)

    outcome = sync_ohlcv(client, store, "DOGE-USDT-SWAP", start_ms=START, max_pages=10)

    assert outcome.result.new == 5
    cursors = [call[2] for call in client.calls]
    # Last populated page is [1h, 0h]; its oldest raw ts is START even though
    # that row was dropped, so the next cursor must be START, not START + 1h.
    assert START in cursors, "cursor ignored a dropped row and stalled a window"
    assert len(cursors) == len(set(cursors)), "cursor repeated: paging stalled"


def test_paging_walks_back_to_the_requested_start(store):
    rows = [candle(START + i * HOUR_MS) for i in range(250)]
    client = FakeCandles(rows, page_size=100)

    outcome = sync_ohlcv(client, store, "DOGE-USDT-SWAP", start_ms=START)

    assert outcome.result.new == 250
    assert outcome.oldest_ts == START
    assert outcome.newest_ts == START + 249 * HOUR_MS


def test_bars_before_the_start_are_not_stored(store):
    rows = [candle(START + i * HOUR_MS) for i in range(10)]
    client = FakeCandles(rows)
    cutoff = START + 5 * HOUR_MS

    outcome = sync_ohlcv(client, store, "DOGE-USDT-SWAP", start_ms=cutoff)

    assert outcome.oldest_ts == cutoff
    assert outcome.result.new == 5


def test_prices_are_stored_as_numbers_not_strings(store):
    client = FakeCandles([candle(START, close=0.07169)])

    sync_ohlcv(client, store, "DOGE-USDT-SWAP", start_ms=START)

    frame = store.load_ohlcv("DOGE-USDT-SWAP", "1h")
    assert frame["close"].iloc[0] == pytest.approx(0.07169)
    assert frame["high"].iloc[0] == pytest.approx(2.0)


def test_resync_is_idempotent(store):
    rows = [candle(START + i * HOUR_MS) for i in range(10)]
    client = FakeCandles(rows)

    first = sync_ohlcv(client, store, "DOGE-USDT-SWAP", start_ms=START)
    second = sync_ohlcv(client, store, "DOGE-USDT-SWAP", start_ms=START)

    assert first.result.new == 10
    assert second.result.new == 0
    assert len(store.load_ohlcv("DOGE-USDT-SWAP", "1h")) == 10


class FailsOnThirdPage(FakeCandles):
    """Dies partway through a walk, like a dropped connection."""

    def history_candles(self, inst_id, bar="1H", before_ts=None, limit=100):
        if len(self.calls) >= 2:
            raise RuntimeError("connection reset")
        return super().history_candles(inst_id, bar, before_ts, limit)


def test_interrupted_sync_keeps_the_pages_it_already_fetched(store):
    # A full history is ~500 pages. Buffering all of it and flushing at the
    # end means a failure at page 499 stores nothing and resumes from nowhere.
    rows = [candle(START + i * HOUR_MS) for i in range(10)]
    client = FailsOnThirdPage(rows, page_size=2)

    with pytest.raises(RuntimeError):
        sync_ohlcv(client, store, "DOGE-USDT-SWAP", start_ms=START, max_pages=10)

    stored = store.load_ohlcv("DOGE-USDT-SWAP", "1h")
    assert len(stored) == 4, "pages fetched before the failure must survive it"


def test_rerunning_after_an_interruption_completes_the_history(store):
    # The property that actually matters, and the one the old resumption
    # logic did not have. OKX pages newest-first, so an interruption leaves
    # the *oldest* bars missing; resuming near the newest stored bar fetches
    # nothing and calls the hole finished.
    rows = [candle(START + i * HOUR_MS) for i in range(10)]

    with pytest.raises(RuntimeError):
        sync_ohlcv(
            FailsOnThirdPage(rows, page_size=2),
            store,
            "DOGE-USDT-SWAP",
            start_ms=START,
            max_pages=10,
        )
    assert len(store.load_ohlcv("DOGE-USDT-SWAP", "1h")) == 4

    resume = incremental_start(store, "DOGE-USDT-SWAP", "1h", default_start_ms=START)
    assert resume == START, "an unfinished walk must restart, not resume at the tip"

    sync_ohlcv(FakeCandles(rows, page_size=2), store, "DOGE-USDT-SWAP", start_ms=resume)

    stored = store.load_ohlcv("DOGE-USDT-SWAP", "1h")
    assert len(stored) == 10, "the re-run must fill the tail the interruption left"


def test_incremental_start_refetches_the_newest_stored_bar(store):
    rows = [candle(START + i * HOUR_MS) for i in range(5)]
    sync_ohlcv(FakeCandles(rows), store, "DOGE-USDT-SWAP", start_ms=START)

    resume = incremental_start(store, "DOGE-USDT-SWAP", "1h", default_start_ms=START)

    # One bar back: a tail written mid-page gets re-read rather than trusted.
    assert resume == START + 3 * HOUR_MS


def test_a_completed_walk_is_not_undone_by_the_nightly_top_up(store):
    # The top-up asks only for the last bar onwards. If that shrank the record
    # of what has been covered, the following night would decide the history
    # was never walked and start the whole backfill again.
    rows = [candle(START + i * HOUR_MS) for i in range(5)]
    sync_ohlcv(FakeCandles(rows), store, "DOGE-USDT-SWAP", start_ms=START)

    first = incremental_start(store, "DOGE-USDT-SWAP", "1h", default_start_ms=START)
    sync_ohlcv(FakeCandles(rows), store, "DOGE-USDT-SWAP", start_ms=first)
    second = incremental_start(store, "DOGE-USDT-SWAP", "1h", default_start_ms=START)

    assert second == first, "a completed history must stay completed"


def test_an_instrument_listed_after_the_requested_start_still_resumes(store):
    # History that simply does not go back that far is not an interruption:
    # the walk ran out of candles, which is a finished walk. Treating it as a
    # hole would re-walk the entire history every single night.
    rows = [candle(START + i * HOUR_MS) for i in range(5)]
    sync_ohlcv(
        FakeCandles(rows), store, "DOGE-USDT-SWAP", start_ms=START - 1000 * HOUR_MS
    )

    resume = incremental_start(
        store, "DOGE-USDT-SWAP", "1h", default_start_ms=START - 1000 * HOUR_MS
    )
    assert resume == START + 3 * HOUR_MS


def test_incremental_start_falls_back_when_nothing_is_stored(store):
    assert incremental_start(store, "DOGE-USDT-SWAP", "1h", default_start_ms=START) == START


# ---- concurrent backfill ---------------------------------------------------


# Enough hourly bars (80 pages) to split into several windows, so the
# multi-window path is actually exercised rather than collapsing to one walk.
MULTI_WINDOW_BARS = 8000


def _now_after(rows):
    """A clock just past the newest row, so partitioning has an upper edge."""
    return max(int(r[0]) for r in rows) + HOUR_MS


def test_concurrent_backfill_stores_the_same_bars_as_a_sequential_walk(store):
    # The whole point: splitting one instrument's range across windows must not
    # drop or duplicate a bar.
    rows = [candle(START + i * HOUR_MS, close=float(i)) for i in range(MULTI_WINDOW_BARS)]

    results, errors = sync_ohlcv_concurrent(
        lambda: FakeCandles(rows),
        store,
        [SyncJob("DOGE-USDT-SWAP", START)],
        now_ms=_now_after(rows),
        concurrency=6,
    )

    assert errors == {}
    frame = store.load_ohlcv("DOGE-USDT-SWAP", "1h")
    assert len(frame) == MULTI_WINDOW_BARS
    # Every close survived intact and in order — no window overwrote another's.
    assert list(frame["close"]) == [float(i) for i in range(MULTI_WINDOW_BARS)]
    (result,) = results
    assert result.result.new == MULTI_WINDOW_BARS
    assert result.oldest_ts == START
    assert result.newest_ts == START + (MULTI_WINDOW_BARS - 1) * HOUR_MS
    assert result.complete


def test_concurrent_backfill_runs_windows_in_parallel(store):
    # Latency, not the rate limit, is the cost being cut, so the fetchers must
    # actually overlap. A barrier that only releases once `concurrency` calls
    # are in flight deadlocks unless the walks truly run at once.
    rows = [candle(START + i * HOUR_MS) for i in range(MULTI_WINDOW_BARS)]
    concurrency = 4
    barrier = threading.Barrier(concurrency, timeout=5)

    class Overlapping(FakeCandles):
        def history_candles(self, inst_id, bar="1H", before_ts=None, limit=100):
            if not getattr(self, "_synced", False):
                self._synced = True
                barrier.wait()  # raises BrokenBarrierError on timeout
            return super().history_candles(inst_id, bar, before_ts, limit)

    _, errors = sync_ohlcv_concurrent(
        lambda: Overlapping(rows),
        store,
        [SyncJob("DOGE-USDT-SWAP", START)],
        now_ms=_now_after(rows),
        concurrency=concurrency,
    )

    assert errors == {}
    assert len(store.load_ohlcv("DOGE-USDT-SWAP", "1h")) == MULTI_WINDOW_BARS


def test_concurrent_backfill_covers_several_instruments(store):
    rows_a = [candle(START + i * HOUR_MS, close=1.0) for i in range(150)]
    rows_b = [candle(START + i * HOUR_MS, close=2.0) for i in range(150)]
    rows_by_inst = {"DOGE-USDT-SWAP": rows_a, "BTC-USDT-SWAP": rows_b}

    def factory():
        # One client per worker; it serves whichever instrument it is asked
        # about from the shared row sets.
        class MultiInst(FakeCandles):
            def __init__(self):
                super().__init__([])

            def history_candles(self, inst_id, bar="1H", before_ts=None, limit=100):
                self.rows = sorted(
                    rows_by_inst[inst_id], key=lambda r: int(r[0]), reverse=True
                )
                return super().history_candles(inst_id, bar, before_ts, limit)

        return MultiInst()

    results, errors = sync_ohlcv_concurrent(
        factory,
        store,
        [SyncJob("DOGE-USDT-SWAP", START), SyncJob("BTC-USDT-SWAP", START)],
        now_ms=_now_after(rows_a),
        concurrency=4,
    )

    assert errors == {}
    assert len(store.load_ohlcv("DOGE-USDT-SWAP", "1h")) == 150
    assert len(store.load_ohlcv("BTC-USDT-SWAP", "1h")) == 150
    assert {r.inst_id for r in results} == {"DOGE-USDT-SWAP", "BTC-USDT-SWAP"}


def test_concurrent_backfill_marks_a_completed_history_resumable(store):
    count = MULTI_WINDOW_BARS
    rows = [candle(START + i * HOUR_MS) for i in range(count)]

    sync_ohlcv_concurrent(
        lambda: FakeCandles(rows),
        store,
        [SyncJob("DOGE-USDT-SWAP", START)],
        now_ms=_now_after(rows),
        concurrency=4,
    )

    # A finished concurrent walk must record its span, or the next run would
    # decide the history was never covered and re-walk all of it. Resumption
    # lands one bar before the newest, to re-read a tail written mid-page.
    newest = START + (count - 1) * HOUR_MS
    resume = incremental_start(store, "DOGE-USDT-SWAP", "1h", default_start_ms=START)
    assert resume == newest - HOUR_MS


def test_concurrent_backfill_isolates_a_failing_instrument(store):
    good = [candle(START + i * HOUR_MS) for i in range(150)]

    def factory():
        class Selective(FakeCandles):
            def __init__(self):
                super().__init__([])

            def history_candles(self, inst_id, bar="1H", before_ts=None, limit=100):
                if inst_id == "BROKEN":
                    raise RuntimeError("connection reset")
                self.rows = sorted(good, key=lambda r: int(r[0]), reverse=True)
                return super().history_candles(inst_id, bar, before_ts, limit)

        return Selective()

    _, errors = sync_ohlcv_concurrent(
        factory,
        store,
        [SyncJob("DOGE-USDT-SWAP", START), SyncJob("BROKEN", START)],
        now_ms=_now_after(good),
        concurrency=4,
    )

    # The healthy instrument still lands; the broken one is reported, not raised.
    assert "BROKEN" in errors
    assert len(store.load_ohlcv("DOGE-USDT-SWAP", "1h")) == 150
    # And the broken one is left un-finished, so a rerun restarts its walk.
    assert incremental_start(store, "BROKEN", "1h", default_start_ms=START) == START


def test_concurrent_backfill_reports_progress_per_window(store):
    # Progress is windows-done/total, not instruments-done/total, so a caller
    # watching it sees movement throughout a single big instrument's backfill.
    rows = [candle(START + i * HOUR_MS) for i in range(MULTI_WINDOW_BARS)]
    updates: list[tuple[int, int, int]] = []

    results, errors = sync_ohlcv_concurrent(
        lambda: FakeCandles(rows),
        store,
        [SyncJob("DOGE-USDT-SWAP", START)],
        now_ms=_now_after(rows),
        concurrency=6,
        on_progress=lambda done, total, new_rows: updates.append((done, total, new_rows)),
    )

    assert errors == {}
    assert updates  # at least one window landed
    dones = [done for done, _total, _new in updates]
    totals = {total for _done, total, _new in updates}
    # Every update agrees on the total window count, and `done` counts up by
    # one to that total with no update skipped or repeated.
    assert len(totals) == 1
    assert dones == list(range(1, len(updates) + 1))
    (total,) = totals
    assert dones[-1] == total
    # The final cumulative tally matches what actually landed in the store.
    (result,) = results
    assert updates[-1][2] == result.result.new == MULTI_WINDOW_BARS


def test_concurrent_backfill_reports_progress_through_a_failing_window(store):
    # A window that raises must still advance the counter — otherwise a caller
    # rendering a progress bar would stall forever on a partial failure.
    good = [candle(START + i * HOUR_MS) for i in range(150)]

    def factory():
        class Selective(FakeCandles):
            def __init__(self):
                super().__init__([])

            def history_candles(self, inst_id, bar="1H", before_ts=None, limit=100):
                if inst_id == "BROKEN":
                    raise RuntimeError("connection reset")
                self.rows = sorted(good, key=lambda r: int(r[0]), reverse=True)
                return super().history_candles(inst_id, bar, before_ts, limit)

        return Selective()

    updates: list[tuple[int, int, int]] = []
    _, errors = sync_ohlcv_concurrent(
        factory,
        store,
        [SyncJob("DOGE-USDT-SWAP", START), SyncJob("BROKEN", START)],
        now_ms=_now_after(good),
        concurrency=4,
        on_progress=lambda done, total, new_rows: updates.append((done, total, new_rows)),
    )

    assert "BROKEN" in errors
    (total,) = {total for _done, total, _new in updates}
    assert total == 2
    assert updates[-1][0] == total


def test_concurrent_backfill_reaches_the_requested_start_across_windows(store):
    # A window that stops short would leave a hole between two others. Pin that
    # the union of windows spans [start, newest] with no gaps.
    count = MULTI_WINDOW_BARS
    rows = [candle(START + i * HOUR_MS) for i in range(count)]

    sync_ohlcv_concurrent(
        lambda: FakeCandles(rows),
        store,
        [SyncJob("DOGE-USDT-SWAP", START)],
        now_ms=_now_after(rows),
        concurrency=8,
    )

    frame = store.load_ohlcv("DOGE-USDT-SWAP", "1h")
    stored_ts = [int(ts.timestamp() * 1000) for ts in frame.index]
    expected = [START + i * HOUR_MS for i in range(count)]
    assert stored_ts == expected, "windows left a gap or overlap in the timeline"
