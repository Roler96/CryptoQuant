"""Storage layer: dedupe, coverage and the archive-run audit trail."""

import sqlite3

import pytest

from cq.data.store import Store, WriteResult


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "test.db") as s:
        yield s


def _funding_rows(times, inst_id="DOGE-USDT-SWAP"):
    return [(inst_id, t, 0.0001, 0.0001, 1_700_000_000_000) for t in times]


def test_upsert_funding_counts_only_new_rows(store):
    first = store.upsert_funding(_funding_rows([1000, 2000, 3000]))
    assert first == WriteResult(seen=3, new=3)

    # Re-archiving overlapping history is the normal case: the sweep always
    # re-reads the full window. Only genuinely new settlements must count.
    second = store.upsert_funding(_funding_rows([2000, 3000, 4000]))
    assert second == WriteResult(seen=3, new=1)

    count, lo, hi = store.funding_coverage("DOGE-USDT-SWAP")
    assert (count, lo, hi) == (4, 1000, 4000)


def test_duplicate_keys_in_one_batch_count_as_one_new_row(store):
    # A single settlement arriving twice in the same batch — the signature of a
    # paging bug that hands back an overlapping page — writes exactly one row.
    # `new` must reflect the row actually added, not the two keys seen, or a
    # duplicated page would masquerade as genuine growth in the audit trail.
    result = store.upsert_funding(_funding_rows([5000, 5000]))
    assert result == WriteResult(seen=2, new=1)
    assert store.funding_coverage("DOGE-USDT-SWAP") == (1, 5000, 5000)


def test_re_archiving_corrects_a_stored_rate(store):
    # A settlement swept moments after it fires carries the predicted rate and
    # often no realized one at all. The next sweep brings the measurement, and
    # it has to be allowed to land: `INSERT OR IGNORE` kept the prediction
    # forever and every swap backtest then charged a forecast as if measured.
    store.upsert_funding([("DOGE-USDT-SWAP", 1000, 0.0001, None, 1)])
    store.upsert_funding([("DOGE-USDT-SWAP", 1000, 0.0001, 0.00013, 2)])

    row = store._conn.execute(
        "SELECT realized_rate, fetched_at FROM funding WHERE funding_time=1000"
    ).fetchone()
    assert row["realized_rate"] == 0.00013
    assert row["fetched_at"] == 2


def test_a_row_that_violates_the_schema_raises_instead_of_vanishing(store):
    # `INSERT OR IGNORE` suppressed NOT NULL violations exactly as quietly as
    # duplicates, so malformed rows left no trace anywhere.
    with pytest.raises(sqlite3.IntegrityError):
        store.upsert_funding([("DOGE-USDT-SWAP", 1000, None, None, 1)])

    assert store.funding_coverage("DOGE-USDT-SWAP") == (0, None, None)


def test_a_refetched_candle_corrects_the_stored_one(store):
    # OKX revises candles shortly after they close. The exchange's later value
    # is the right one; keeping the first copy pins the bar to whatever the
    # tape said in the second after it closed.
    store.upsert_ohlcv([("DOGE-USDT", "1h", 1000, 1.0, 2.0, 0.5, 1.5, 100.0, 150.0)])
    result = store.upsert_ohlcv(
        [("DOGE-USDT", "1h", 1000, 1.0, 2.5, 0.5, 1.6, 120.0, 180.0)]
    )

    assert result == WriteResult(seen=1, new=0), "a correction is not a new bar"
    frame = store.load_ohlcv("DOGE-USDT", "1h")
    assert frame["high"].iloc[0] == 2.5
    assert frame["close"].iloc[0] == 1.6


def test_empty_upsert_is_a_noop(store):
    assert store.upsert_funding([]) == WriteResult(0, 0)
    assert store.funding_coverage("DOGE-USDT-SWAP") == (0, None, None)


def test_open_interest_is_keyed_by_currency_and_timestamp(store):
    rows = [("DOGE", 1000, 95.0, 13.0, 1), ("DOGE", 2000, 96.0, 14.0, 1)]
    assert store.upsert_open_interest(rows).new == 2
    assert store.upsert_open_interest(rows).new == 0
    assert store.open_interest_coverage("DOGE") == (2, 1000, 2000)


def test_ohlcv_is_keyed_per_timeframe(store):
    base = ("DOGE-USDT", "1h", 1000, 1.0, 2.0, 0.5, 1.5, 100.0, 150.0)
    other_tf = ("DOGE-USDT", "4h", 1000, 1.0, 2.0, 0.5, 1.5, 100.0, 150.0)
    assert store.upsert_ohlcv([base]).new == 1
    # Same instrument and timestamp but a different timeframe is a distinct row.
    assert store.upsert_ohlcv([other_tf]).new == 1
    assert store.upsert_ohlcv([base]).new == 0


def test_archive_run_records_success(store):
    run_id = store.start_run("funding", "DOGE-USDT-SWAP", 1000)
    store.finish_run(run_id, 2000, WriteResult(seen=10, new=4), ok=True)

    run = store.recent_runs()[0]
    assert run["kind"] == "funding"
    assert run["target"] == "DOGE-USDT-SWAP"
    assert (run["rows_seen"], run["rows_new"]) == (10, 4)
    assert run["ok"] == 1
    assert run["error"] is None
    assert run["finished_at"] == 2000


def test_archive_run_records_failure_with_reason(store):
    run_id = store.start_run("funding", "ETH-USDT-SWAP", 1000)
    store.finish_run(run_id, 1500, WriteResult(0, 0), ok=False, error="boom")

    run = store.recent_runs()[0]
    assert run["ok"] == 0
    assert run["error"] == "boom"


def test_unfinished_run_is_visible_as_incomplete(store):
    # A crashed archiver must be distinguishable from one that never started.
    store.start_run("funding", "BTC-USDT-SWAP", 1000)
    run = store.recent_runs()[0]
    assert run["finished_at"] is None
    assert run["ok"] == 0
