"""The data subcommands: what they read, and when they report failure.

These run against a temporary database and never touch the network.
"""

import argparse

import pytest

from cq.cli import build_parser
from cq.data import commands as data_commands
from cq.data.commands import cmd_coverage, cmd_quality
from cq.data.store import Store
from cq.universe import DEFAULT_UNIVERSE_PATH, PACKAGED_UNIVERSE_PATH, load_universe

HOUR_MS = 3_600_000
MIN5_MS = 5 * 60_000
START = 1_700_000_000_000 - (1_700_000_000_000 % (24 * HOUR_MS))


@pytest.fixture
def universe_file(tmp_path):
    path = tmp_path / "universe.yaml"
    path.write_text("spot:\n  - DOGE-USDT\nswap: []\n", encoding="utf-8")
    return path


def bars(store, count, inst_id="DOGE-USDT", start=START):
    store.upsert_ohlcv(
        [
            (inst_id, "1h", start + i * HOUR_MS, 1.0, 2.0, 0.5, 1.5, 100.0, 150.0)
            for i in range(count)
        ]
    )


def quality_args(db, universe, timeframe="1h"):
    return argparse.Namespace(
        db=str(db), universe=str(universe), timeframe=timeframe, show_gaps=5
    )


def coverage_args(db, universe):
    return argparse.Namespace(db=str(db), universe=str(universe))


def test_sync_cli_accepts_a_5m_timeframe():
    args = build_parser().parse_args(["data", "sync", "--timeframe", "5m"])

    assert args.timeframe == "5m"


def test_sync_uses_the_requested_timeframe_for_resume_and_fetch(
    monkeypatch, tmp_path, universe_file
):
    observed = {}

    class FakeClient:
        def __init__(self, rate_limiter=None):
            pass

        def milliseconds(self):
            return START

    def fake_incremental_start(store, inst_id, timeframe, default_start_ms):
        observed["resume_timeframe"] = timeframe
        return default_start_ms

    def fake_sync(client_factory, store, jobs, **kwargs):
        observed["fetch_timeframe"] = kwargs["timeframe"]
        return [], {"DOGE-USDT": "deliberate test failure"}

    monkeypatch.setattr(data_commands, "OkxPublicClient", FakeClient)
    monkeypatch.setattr(data_commands, "incremental_start", fake_incremental_start)
    monkeypatch.setattr(data_commands, "sync_ohlcv_concurrent", fake_sync)
    args = build_parser().parse_args(
        [
            "data",
            "sync",
            "--db",
            str(tmp_path / "cq.db"),
            "--universe",
            str(universe_file),
            "--timeframe",
            "5m",
        ]
    )

    assert data_commands.cmd_sync(args) == 1
    assert observed == {"resume_timeframe": "5m", "fetch_timeframe": "5m"}


def test_coverage_lists_every_stored_timeframe(tmp_path, universe_file, capsys):
    # A 5m series used to be invisible: coverage only ever queried the 1h base,
    # so a whole resolution stored in the database went unreported.
    db = tmp_path / "cq.db"
    with Store(db) as store:
        bars(store, 24)  # 1h
        store.upsert_ohlcv(
            [
                ("DOGE-USDT", "5m", START + i * MIN5_MS, 1.0, 2.0, 0.5, 1.5, 100.0, 150.0)
                for i in range(288)
            ]
        )

    code = cmd_coverage(coverage_args(db, universe_file))

    out = capsys.readouterr().out
    assert "5m  DOGE-USDT" in out, out
    assert "1h  DOGE-USDT" in out, out
    # Ordered by bar size: the finer 5m line comes before 1h.
    assert out.index("5m  DOGE-USDT") < out.index("1h  DOGE-USDT"), out
    assert code == 0


def test_coverage_keeps_a_base_line_for_an_unsynced_instrument(tmp_path, universe_file, capsys):
    # Showing every stored timeframe must not drop the "this was never synced"
    # signal for an instrument that has no rows at all.
    db = tmp_path / "cq.db"
    Store(db).close()

    code = cmd_coverage(coverage_args(db, universe_file))

    out = capsys.readouterr().out
    assert "1h  DOGE-USDT" in out, out
    assert "never" in out, out
    assert code == 0


def test_quality_on_a_higher_timeframe_resamples_the_stored_base(tmp_path, universe_file, capsys):
    # A timeframe not fetched directly is derived from the default 1h base.
    db = tmp_path / "cq.db"
    with Store(db) as store:
        bars(store, 24)

    code = cmd_quality(quality_args(db, universe_file, timeframe="4h"))

    out = capsys.readouterr().out
    assert "6 bars" in out, out
    assert code == 0


def test_quality_checks_a_directly_synced_5m_series(tmp_path, universe_file, capsys):
    db = tmp_path / "cq.db"
    with Store(db) as store:
        store.upsert_ohlcv(
            [
                ("DOGE-USDT", "5m", START + i * MIN5_MS, 1.0, 2.0, 0.5, 1.5, 100.0, 150.0)
                for i in range(12)
            ]
        )

    code = cmd_quality(quality_args(db, universe_file, timeframe="5m"))

    assert "12 bars" in capsys.readouterr().out
    assert code == 0


def test_quality_reports_failure_on_an_empty_database(tmp_path, universe_file, capsys):
    # An unsynced database exiting zero is how a cron job reports success for
    # data it never had.
    db = tmp_path / "cq.db"
    Store(db).close()

    code = cmd_quality(quality_args(db, universe_file))

    assert "no data" in capsys.readouterr().out
    assert code == 1


def test_quality_still_passes_on_a_contiguous_series(tmp_path, universe_file):
    db = tmp_path / "cq.db"
    with Store(db) as store:
        bars(store, 24)

    assert cmd_quality(quality_args(db, universe_file)) == 0


# ---- the universe travels with the package -----------------------------


def test_the_default_universe_is_packaged_with_the_code():
    # The wheel installs a `cq` command whose every subcommand starts by
    # reading the universe, so a file outside the package makes the installed
    # CLI work only inside the repository.
    assert PACKAGED_UNIVERSE_PATH.exists()
    assert "DOGE-USDT-SWAP" in load_universe(PACKAGED_UNIVERSE_PATH).swap


def test_the_universe_loads_with_no_working_directory_override(monkeypatch, tmp_path):
    # The failure this reproduces: `cd /tmp && cq data coverage`.
    monkeypatch.chdir(tmp_path)
    assert not DEFAULT_UNIVERSE_PATH.exists()
    assert load_universe().all_instruments


def test_a_working_directory_override_takes_precedence(monkeypatch, tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "universe.yaml").write_text(
        "spot:\n  - PEPE-USDT\nswap: []\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    assert load_universe().spot == ("PEPE-USDT",)


def test_an_explicit_universe_that_does_not_exist_is_an_error(tmp_path):
    # The fallback is for the default path only: a mistyped --universe must
    # not quietly load a different set of instruments.
    with pytest.raises(FileNotFoundError):
        load_universe(tmp_path / "nope.yaml")
