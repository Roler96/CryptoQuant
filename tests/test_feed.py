"""Feeds: both must yield closed bars only, and yield each exactly once."""

import ccxt
import pytest

from cq.context import Bar
from cq.core.clock import HOUR_MS
from cq.data.feed import (
    FeedStalledError,
    HistoricalFeed,
    LiveFeed,
    WarmupError,
    load_series,
    recent_closed_bars,
    series_from_bars,
)
from cq.data.store import Store

DAY0 = 1_609_459_200_000  # 2021-01-01 00:00 UTC


def candle(ts, close=1.0, confirm="1"):
    return [str(ts), "1.0", "2.0", "0.5", str(close), "10", "10", "20", confirm]


class FakeLiveSource:
    """Returns a fixed page; the test controls the clock separately."""

    def __init__(self, page):
        self.page = page

    def milliseconds(self) -> int:
        return 0

    def history_candles(self, inst_id, bar="1H", before_ts=None, limit=100):
        return self.page


class SequencedLiveSource(FakeLiveSource):
    """Returns or raises each scripted result once."""

    def __init__(self, results):
        super().__init__([])
        self.results = list(results)
        self.calls = 0

    def history_candles(self, inst_id, bar="1H", before_ts=None, limit=100):
        self.calls += 1
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


class PagedLiveSource:
    def __init__(self, rows: list[list[str]]):
        self.rows = sorted(rows, key=lambda row: int(row[0]), reverse=True)

    def milliseconds(self) -> int:
        return DAY0 + 20 * HOUR_MS

    def history_candles(
        self, inst_id: str, bar: str = "1H", before_ts: int | None = None, limit: int = 100
    ) -> list[list[str]]:
        eligible = self.rows
        if before_ts is not None:
            eligible = [row for row in eligible if int(row[0]) < before_ts]
        return eligible[:limit]


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "test.db") as s:
        yield s


def seed(store, inst_id="DOGE-USDT", count=8, start=DAY0):
    rows = [
        (inst_id, "1h", start + i * HOUR_MS, 1.0 + i, 2.0 + i, 0.5 + i, 1.5 + i, 10.0, 15.0)
        for i in range(count)
    ]
    store.upsert_ohlcv(rows)


# ---- historical --------------------------------------------------------


def test_historical_feed_replays_in_order(store):
    seed(store, count=5)
    feed = HistoricalFeed(load_series(store, "DOGE-USDT"))

    bars = list(feed)

    assert len(bars) == 5
    assert [b.ts for b in bars] == sorted(b.ts for b in bars)
    assert bars[0].ts == DAY0
    assert bars[-1].ts == DAY0 + 4 * HOUR_MS


def test_historical_feed_carries_prices_through(store):
    seed(store, count=3)
    bars = list(HistoricalFeed(load_series(store, "DOGE-USDT")))
    assert bars[1].open == 2.0
    assert bars[1].high == 3.0
    assert bars[1].low == 1.5
    assert bars[1].close == 2.5


def test_loading_a_higher_timeframe_resamples_from_the_base(store):
    seed(store, count=9)  # 8 complete hours plus one leftover
    series = load_series(store, "DOGE-USDT", "4h")

    assert len(series) == 2, "the incomplete trailing period must not appear"
    assert series.timeframe == "4h"
    assert int(series.ts[0]) == DAY0


def test_empty_store_yields_no_bars(store):
    assert list(HistoricalFeed(load_series(store, "DOGE-USDT"))) == []


# ---- live --------------------------------------------------------------


def test_live_feed_skips_the_unclosed_candle():
    page = [candle(DAY0 + HOUR_MS, confirm="0"), candle(DAY0, confirm="1")]
    feed = LiveFeed(FakeLiveSource(page), "DOGE-USDT", now_ms=lambda: DAY0 + 2 * HOUR_MS)

    bars = feed.poll()

    assert [b.ts for b in bars] == [DAY0]


def test_live_feed_distrusts_a_confirm_flag_the_clock_contradicts():
    # confirm=1 on a bar whose hour has not elapsed. Either guard alone has
    # been wrong before, so both must agree.
    page = [candle(DAY0, confirm="1")]
    feed = LiveFeed(FakeLiveSource(page), "DOGE-USDT", now_ms=lambda: DAY0 + HOUR_MS - 1)

    assert feed.poll() == []


def test_live_feed_emits_a_bar_the_instant_it_closes():
    page = [candle(DAY0, confirm="1")]
    feed = LiveFeed(FakeLiveSource(page), "DOGE-USDT", now_ms=lambda: DAY0 + HOUR_MS)

    assert [b.ts for b in feed.poll()] == [DAY0]


def test_live_feed_never_emits_the_same_bar_twice():
    page = [candle(DAY0 + HOUR_MS), candle(DAY0)]
    feed = LiveFeed(FakeLiveSource(page), "DOGE-USDT", now_ms=lambda: DAY0 + 3 * HOUR_MS)

    first = feed.poll()
    second = feed.poll()

    assert [b.ts for b in first] == [DAY0, DAY0 + HOUR_MS]
    assert second == [], "a repeated poll must not replay bars"


def test_live_feed_returns_bars_oldest_first():
    # OKX serves newest-first; the engine consumes chronologically.
    page = [candle(DAY0 + 2 * HOUR_MS), candle(DAY0 + HOUR_MS), candle(DAY0)]
    feed = LiveFeed(FakeLiveSource(page), "DOGE-USDT", now_ms=lambda: DAY0 + 4 * HOUR_MS)

    assert [b.ts for b in feed.poll()] == [DAY0, DAY0 + HOUR_MS, DAY0 + 2 * HOUR_MS]


def test_live_feed_picks_up_a_later_bar_after_a_gap_in_polling():
    page = [candle(DAY0)]
    source = FakeLiveSource(page)
    now = [DAY0 + HOUR_MS]
    feed = LiveFeed(source, "DOGE-USDT", now_ms=lambda: now[0])
    feed.poll()

    source.page = [candle(DAY0 + 3 * HOUR_MS), candle(DAY0)]
    now[0] = DAY0 + 4 * HOUR_MS
    assert [b.ts for b in feed.poll()] == [DAY0 + 3 * HOUR_MS]


def test_live_feed_iterator_recovers_after_a_transient_poll_failure():
    source = SequencedLiveSource(
        [ccxt.RequestTimeout("network blip"), [candle(DAY0)]]
    )
    sleeps = []
    feed = LiveFeed(
        source,
        "DOGE-USDT",
        poll_seconds=7.0,
        now_ms=lambda: DAY0 + HOUR_MS,
        sleep=sleeps.append,
    )

    bar = next(iter(feed))

    assert bar.ts == DAY0
    assert source.calls == 2
    assert sleeps == [7.0]


def test_live_feed_priming_also_recovers_after_a_transient_failure():
    source = SequencedLiveSource(
        [ccxt.ExchangeNotAvailable("temporary outage"), [candle(DAY0)]]
    )
    sleeps = []
    feed = LiveFeed(
        source,
        "DOGE-USDT",
        poll_seconds=3.0,
        now_ms=lambda: DAY0 + HOUR_MS,
        sleep=sleeps.append,
    )

    assert [bar.ts for bar in feed.prime()] == [DAY0]
    assert source.calls == 2
    assert sleeps == [3.0]


def test_live_feed_raises_when_the_next_closed_bar_is_overdue():
    now = [DAY0 + HOUR_MS]
    feed = LiveFeed(
        FakeLiveSource([candle(DAY0)]),
        "DOGE-USDT",
        stall_grace_seconds=120.0,
        now_ms=lambda: now[0],
    )
    assert [bar.ts for bar in feed.poll()] == [DAY0]

    now[0] = DAY0 + 2 * HOUR_MS + 120_000 - 1
    assert feed.poll() == []

    now[0] += 1
    with pytest.raises(FeedStalledError, match=r"next bar is overdue by 120\.0s"):
        feed.poll()


def test_live_feed_raises_when_no_initial_closed_bar_ever_appears():
    now = [DAY0]
    feed = LiveFeed(
        FakeLiveSource([candle(DAY0, confirm="0")]),
        "DOGE-USDT",
        stall_grace_seconds=30.0,
        now_ms=lambda: now[0],
    )
    assert feed.poll() == []

    now[0] += 30_000
    with pytest.raises(FeedStalledError, match=r"no closed bar was visible for 30\.0s"):
        feed.poll()


def test_recent_closed_bars_pages_an_exact_contiguous_prefix():
    rows = [candle(DAY0 + i * HOUR_MS) for i in range(12)]

    warmup = recent_closed_bars(PagedLiveSource(rows), "DOGE-USDT", "1h", 11)

    assert [bar.ts for bar in warmup] == [DAY0 + i * HOUR_MS for i in range(1, 12)]


def test_recent_closed_bars_rejects_a_gap():
    rows = [candle(DAY0 + i * HOUR_MS) for i in (0, 1, 3)]

    with pytest.raises(WarmupError, match="not contiguous"):
        recent_closed_bars(PagedLiveSource(rows), "DOGE-USDT", "1h", 3)


# ---- shared protocol ---------------------------------------------------


def test_both_feeds_produce_the_same_bar_type(store):
    seed(store, count=2)
    historical = list(HistoricalFeed(load_series(store, "DOGE-USDT")))
    live = LiveFeed(
        FakeLiveSource([candle(DAY0)]), "DOGE-USDT", now_ms=lambda: DAY0 + HOUR_MS
    ).poll()

    assert isinstance(historical[0], Bar)
    assert isinstance(live[0], Bar)


def test_series_from_bars_round_trips(store):
    seed(store, count=4)
    bars = list(HistoricalFeed(load_series(store, "DOGE-USDT")))
    rebuilt = series_from_bars("DOGE-USDT", "1h", bars)

    assert len(rebuilt) == 4
    assert int(rebuilt.ts[0]) == DAY0
    assert float(rebuilt.close[-1]) == bars[-1].close
