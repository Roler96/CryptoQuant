"""Seeding a strategy's warmup from the local store.

One priming poll returns at most ~100 bars; a strategy that needs more (Donchian
needs 121) has the shortfall filled from the store. These cover that the seam is
contiguous, the backlog is preserved verbatim, and a store that cannot cover the
gap yields fewer bars rather than raising.
"""

from __future__ import annotations

from itertools import pairwise

from cq.context import Bar
from cq.core.clock import HOUR_MS
from cq.data.feed import HistoricalFeed, load_series
from cq.data.store import Store
from cq.live.warmup import seed_warmup

DAY0 = 1_700_000_000_000 // HOUR_MS * HOUR_MS  # a clean hour boundary


def _seed_store(path, inst="DOGE-USDT", count=200, start=DAY0):
    with Store(path) as store:
        store.upsert_ohlcv(
            [
                (inst, "1h", start + i * HOUR_MS, 1.0 + i, 2.0 + i, 0.5 + i, 1.5 + i, 10.0, 15.0)
                for i in range(count)
            ]
        )


def test_backlog_already_covers_need_leaves_store_untouched(tmp_path):
    # 300 primed bars exceed a 121-bar need, so seeding just returns the tail —
    # the (empty) store must not be consulted.
    db = tmp_path / "cq.db"  # never created; opening it would fail if touched
    backlog = [
        Bar(ts=i * HOUR_MS, open=1.0, high=1.0, low=1.0, close=1.0, volume=1.0)
        for i in range(300)
    ]
    warmup = seed_warmup(db, backlog, "DOGE-USDT", "1h", warmup_bars=121, requested=8)
    assert len(warmup) == 121
    assert warmup[-1].ts == backlog[-1].ts
    assert warmup == backlog[-121:]


def test_short_backlog_is_filled_from_store(tmp_path):
    db = tmp_path / "cq.db"
    _seed_store(db, count=200)
    with Store(db) as store:
        all_bars = list(HistoricalFeed(load_series(store, "DOGE-USDT", "1h")))
    backlog = all_bars[-100:]  # what one priming poll would return

    warmup = seed_warmup(db, backlog, "DOGE-USDT", "1h", warmup_bars=121, requested=8)

    assert len(warmup) == 121
    ts = [b.ts for b in warmup]
    assert ts == sorted(set(ts))  # strictly ascending, no duplicate at the seam
    assert all(b - a == HOUR_MS for a, b in pairwise(ts))  # contiguous, no gap
    assert warmup[-1].ts == backlog[-1].ts
    assert warmup[-100:] == backlog  # backlog preserved verbatim as the tail
    assert warmup[:-100] == all_bars[-121:-100]  # the fill comes from the store


def test_requested_can_exceed_warmup_bars(tmp_path):
    # A caller asking for a longer rolling window than the strategy strictly
    # needs gets it, still filled from the store.
    db = tmp_path / "cq.db"
    _seed_store(db, count=200)
    with Store(db) as store:
        backlog = list(HistoricalFeed(load_series(store, "DOGE-USDT", "1h")))[-100:]

    warmup = seed_warmup(db, backlog, "DOGE-USDT", "1h", warmup_bars=50, requested=150)
    assert len(warmup) == 150


def test_store_cannot_fill_the_gap_returns_fewer(tmp_path):
    # No bars older than the backlog: the need cannot be met, so the caller gets
    # only what was available and can warn rather than starting under a false
    # sense of a full warmup.
    db = tmp_path / "cq.db"
    _seed_store(db, count=0)
    backlog = [
        Bar(ts=(500 + i) * HOUR_MS, open=1.0, high=1.0, low=1.0, close=1.0, volume=1.0)
        for i in range(100)
    ]
    warmup = seed_warmup(db, backlog, "DOGE-USDT", "1h", warmup_bars=121, requested=8)
    assert warmup == backlog  # only the 100 that existed


def test_empty_backlog_returns_empty(tmp_path):
    db = tmp_path / "cq.db"
    _seed_store(db, count=200)
    assert seed_warmup(db, [], "DOGE-USDT", "1h", warmup_bars=121, requested=8) == []
