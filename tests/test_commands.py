"""The data subcommands: what they read, and when they report failure.

These run against a temporary database and never touch the network.
"""

import argparse

import pytest

from cq.data.commands import cmd_quality
from cq.data.store import Store
from cq.universe import DEFAULT_UNIVERSE_PATH, PACKAGED_UNIVERSE_PATH, load_universe

HOUR_MS = 3_600_000
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


def test_quality_on_a_higher_timeframe_resamples_the_stored_base(tmp_path, universe_file, capsys):
    # Only 1h is ever fetched, so querying the table for 4h returns nothing —
    # and an empty frame used to be reported as a clean series, which reads as
    # "4h is fine" rather than "4h was never checked".
    db = tmp_path / "cq.db"
    with Store(db) as store:
        bars(store, 24)

    code = cmd_quality(quality_args(db, universe_file, timeframe="4h"))

    out = capsys.readouterr().out
    assert "6 bars" in out, out
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
