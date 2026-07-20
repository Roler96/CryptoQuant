"""Derivative archival: paging, parsing, and per-target failure isolation."""

import pytest

from cq.data.derivatives import archive_funding, archive_open_interest
from cq.data.store import Store


class FakeClient:
    """Stands in for OkxPublicClient, recording the paging calls it receives."""

    def __init__(self, pages=None, oi_rows=None, fail_for=None):
        self.pages = pages or {}
        self.oi_rows = oi_rows or {}
        self.fail_for = fail_for or set()
        self.funding_calls = []
        self._clock = 1_700_000_000_000

    def milliseconds(self):
        self._clock += 1
        return self._clock

    def funding_rate_history(self, inst_id, before_ts=None, limit=100):
        self.funding_calls.append((inst_id, before_ts))
        if inst_id in self.fail_for:
            raise RuntimeError("network is down")
        pages = self.pages.get(inst_id, [])
        index = sum(1 for call in self.funding_calls if call[0] == inst_id) - 1
        return pages[index] if index < len(pages) else []

    def open_interest_volume(self, ccy, period="1H"):
        if ccy in self.fail_for:
            raise RuntimeError("network is down")
        return self.oi_rows.get(ccy, [])


def _entry(ms, rate="0.0001"):
    return {
        "instId": "DOGE-USDT-SWAP",
        "fundingTime": str(ms),
        "fundingRate": rate,
        "realizedRate": rate,
    }


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "test.db") as s:
        yield s


def test_funding_pages_backwards_until_history_runs_out(store):
    client = FakeClient(
        pages={
            "DOGE-USDT-SWAP": [
                [_entry(3000), _entry(2000)],
                [_entry(1000)],
                [],  # the wall: OKX serves ~3 months and then returns nothing
            ]
        }
    )

    summary = archive_funding(client, store, ["DOGE-USDT-SWAP"])

    assert summary.ok
    assert summary.rows_new == 3
    # Each page must resume from the oldest row of the previous page, or the
    # sweep would loop over the newest page forever.
    assert client.funding_calls == [
        ("DOGE-USDT-SWAP", None),
        ("DOGE-USDT-SWAP", 2000),
        ("DOGE-USDT-SWAP", 1000),
    ]
    assert store.funding_coverage("DOGE-USDT-SWAP") == (3, 1000, 3000)


def test_funding_stops_at_max_pages(store):
    endless = [[_entry(ms)] for ms in range(9000, 0, -1000)]
    client = FakeClient(pages={"DOGE-USDT-SWAP": endless})

    archive_funding(client, store, ["DOGE-USDT-SWAP"], max_pages=2)

    assert len(client.funding_calls) == 2
    assert store.funding_coverage("DOGE-USDT-SWAP")[0] == 2


def test_funding_rate_is_parsed_as_a_number(store):
    client = FakeClient(pages={"DOGE-USDT-SWAP": [[_entry(1000, "0.00004094")], []]})

    archive_funding(client, store, ["DOGE-USDT-SWAP"])

    row = store._conn.execute("SELECT funding_rate, realized_rate FROM funding").fetchone()
    assert row["funding_rate"] == pytest.approx(0.00004094)
    assert row["realized_rate"] == pytest.approx(0.00004094)


def test_missing_realized_rate_is_stored_as_null_not_zero(store):
    entry = _entry(1000)
    entry["realizedRate"] = ""
    client = FakeClient(pages={"DOGE-USDT-SWAP": [[entry], []]})

    archive_funding(client, store, ["DOGE-USDT-SWAP"])

    row = store._conn.execute("SELECT realized_rate FROM funding").fetchone()
    assert row["realized_rate"] is None


def test_one_failing_instrument_does_not_stop_the_others(store):
    client = FakeClient(
        pages={"DOGE-USDT-SWAP": [[_entry(1000)], []]},
        fail_for={"BTC-USDT-SWAP"},
    )

    summary = archive_funding(client, store, ["BTC-USDT-SWAP", "DOGE-USDT-SWAP"])

    assert not summary.ok
    assert "BTC-USDT-SWAP" in summary.errors
    assert "network is down" in summary.errors["BTC-USDT-SWAP"]
    # The healthy instrument still got archived.
    assert store.funding_coverage("DOGE-USDT-SWAP")[0] == 1

    runs = {(r["kind"], r["target"]): r for r in store.recent_runs()}
    assert runs[("funding", "BTC-USDT-SWAP")]["ok"] == 0
    assert runs[("funding", "DOGE-USDT-SWAP")]["ok"] == 1


def test_open_interest_rows_are_archived(store):
    client = FakeClient(oi_rows={"DOGE": [["2000", "96.0", "14.0"], ["1000", "95.0", "13.0"]]})

    summary = archive_open_interest(client, store, ["DOGE"])

    assert summary.ok
    assert store.open_interest_coverage("DOGE") == (2, 1000, 2000)
    row = store._conn.execute(
        "SELECT oi_usd, volume_usd FROM open_interest WHERE ts=2000"
    ).fetchone()
    assert (row["oi_usd"], row["volume_usd"]) == (96.0, 14.0)


def test_open_interest_failure_is_recorded(store):
    client = FakeClient(fail_for={"ETH"})

    summary = archive_open_interest(client, store, ["ETH"])

    assert not summary.ok
    assert store.recent_runs()[0]["ok"] == 0
