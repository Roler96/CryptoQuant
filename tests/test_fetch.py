"""OHLCV backfill: closed-bar filtering, paging and resumption."""

import pytest

from cq.core.clock import HOUR_MS
from cq.data.fetch import incremental_start, sync_ohlcv
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


def test_interrupted_sync_keeps_the_pages_it_already_fetched(store):
    # A full history is ~500 pages. Buffering all of it and flushing at the
    # end means a failure at page 499 stores nothing and resumes from nowhere.
    class FailsOnThirdPage(FakeCandles):
        def history_candles(self, inst_id, bar="1H", before_ts=None, limit=100):
            if len(self.calls) >= 2:
                raise RuntimeError("connection reset")
            return super().history_candles(inst_id, bar, before_ts, limit)

    rows = [candle(START + i * HOUR_MS) for i in range(10)]
    client = FailsOnThirdPage(rows, page_size=2)

    with pytest.raises(RuntimeError):
        sync_ohlcv(client, store, "DOGE-USDT-SWAP", start_ms=START, max_pages=10)

    stored = store.load_ohlcv("DOGE-USDT-SWAP", "1h")
    assert len(stored) == 4, "pages fetched before the failure must survive it"

    # And a re-run picks up from there rather than starting over.
    resume = incremental_start(store, "DOGE-USDT-SWAP", "1h", default_start_ms=START)
    assert resume > START


def test_incremental_start_refetches_the_newest_stored_bar(store):
    rows = [candle(START + i * HOUR_MS) for i in range(5)]
    sync_ohlcv(FakeCandles(rows), store, "DOGE-USDT-SWAP", start_ms=START)

    resume = incremental_start(store, "DOGE-USDT-SWAP", "1h", default_start_ms=0)

    # One bar back: a tail written mid-page gets re-read rather than trusted.
    assert resume == START + 3 * HOUR_MS


def test_incremental_start_falls_back_when_nothing_is_stored(store):
    assert incremental_start(store, "DOGE-USDT-SWAP", "1h", default_start_ms=START) == START
