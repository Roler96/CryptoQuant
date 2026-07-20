"""CLI wiring for the data subcommands."""

from __future__ import annotations

import argparse
import datetime as dt

from cq.data.derivatives import archive_funding, archive_open_interest
from cq.data.okx import OkxPublicClient
from cq.data.store import DEFAULT_DB_PATH, Store
from cq.universe import DEFAULT_UNIVERSE_PATH, load_universe


def register(subparsers: argparse._SubParsersAction) -> None:
    """Attach every `cq data ...` subcommand to the parser."""
    archive = subparsers.add_parser(
        "archive-derivs",
        help="archive funding rates and open interest (run nightly; history expires)",
    )
    _add_common(archive)
    archive.add_argument(
        "--skip-open-interest", action="store_true", help="archive funding only"
    )
    archive.set_defaults(handler=cmd_archive_derivs)

    coverage = subparsers.add_parser(
        "coverage", help="show what derivative history is stored and how fresh it is"
    )
    _add_common(coverage)
    coverage.set_defaults(handler=cmd_coverage)


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite path")
    parser.add_argument(
        "--universe", default=str(DEFAULT_UNIVERSE_PATH), help="universe YAML path"
    )


def cmd_archive_derivs(args: argparse.Namespace) -> int:
    universe = load_universe(args.universe)
    client = OkxPublicClient()
    failed = False
    with Store(args.db) as store:
        funding = archive_funding(client, store, list(universe.swap))
        print(
            f"funding:       {funding.rows_new:>6} new / {funding.rows_seen} seen "
            f"across {len(universe.swap)} instruments"
        )
        for target, error in funding.errors.items():
            print(f"  FAILED {target}: {error}")
        failed |= not funding.ok

        if not args.skip_open_interest:
            oi = archive_open_interest(
                client, store, list(universe.open_interest_currencies)
            )
            print(
                f"open interest: {oi.rows_new:>6} new / {oi.rows_seen} seen "
                f"across {len(universe.open_interest_currencies)} currencies"
            )
            for target, error in oi.errors.items():
                print(f"  FAILED {target}: {error}")
            failed |= not oi.ok

    return 1 if failed else 0


def cmd_coverage(args: argparse.Namespace) -> int:
    universe = load_universe(args.universe)
    now_ms = int(dt.datetime.now(dt.UTC).timestamp() * 1000)
    with Store(args.db) as store:
        print(f"{'series':<24}{'rows':>7}  {'oldest':<17}{'newest':<17}{'lag':>10}")
        print("-" * 76)
        for inst_id in universe.swap:
            count, lo, hi = store.funding_coverage(inst_id)
            print(_coverage_line(f"funding {inst_id}", count, lo, hi, now_ms))
        for ccy in universe.open_interest_currencies:
            count, lo, hi = store.open_interest_coverage(ccy)
            print(_coverage_line(f"OI {ccy}", count, lo, hi, now_ms))
    return 0


def _coverage_line(label: str, count: int, lo: int | None, hi: int | None, now_ms: int) -> str:
    if not count or lo is None or hi is None:
        return f"{label:<24}{0:>7}  {'-':<17}{'-':<17}{'never':>10}"
    lag_h = (now_ms - hi) / 3_600_000
    return (
        f"{label:<24}{count:>7}  {_fmt(lo):<17}{_fmt(hi):<17}{lag_h:>9.1f}h"
    )


def _fmt(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.UTC).strftime("%Y-%m-%d %H:%M")
