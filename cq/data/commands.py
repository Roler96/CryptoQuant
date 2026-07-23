"""CLI wiring for the data subcommands."""

from __future__ import annotations

import argparse
import datetime as dt

import pandas as pd

from cq.core.clock import BASE_TIMEFRAME, duration_ms
from cq.data.derivatives import archive_funding, archive_open_interest
from cq.data.fetch import incremental_start, sync_ohlcv
from cq.data.okx import OkxPublicClient
from cq.data.quality import check_ohlcv
from cq.data.resample import resample
from cq.data.store import DEFAULT_DB_PATH, Store
from cq.universe import DEFAULT_UNIVERSE_PATH, load_universe

# DOGE-USDT-SWAP does not exist before 2021, and that is the oldest instrument
# in the universe, so it bounds a full backfill.
DEFAULT_HISTORY_START = "2021-01-01"


def register(subparsers: argparse._SubParsersAction) -> None:
    """Attach every `cq data ...` subcommand to the parser."""
    sync = subparsers.add_parser("sync", help="backfill closed OHLCV bars from OKX")
    _add_common(sync)
    sync.add_argument(
        "--start", default=None, help=f"UTC date, default resume or {DEFAULT_HISTORY_START}"
    )
    sync.add_argument("--end", default=None, help="UTC date, exclusive")
    sync.add_argument("--instruments", nargs="*", default=None, help="default: whole universe")
    sync.add_argument(
        "--full", action="store_true", help="re-walk history, ignoring what is stored"
    )
    sync.set_defaults(handler=cmd_sync)

    quality = subparsers.add_parser("quality", help="report gaps and anomalies in stored bars")
    _add_common(quality)
    quality.add_argument("--timeframe", default=BASE_TIMEFRAME)
    quality.add_argument("--show-gaps", type=int, default=5, help="gaps to list per instrument")
    quality.set_defaults(handler=cmd_quality)

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


def cmd_sync(args: argparse.Namespace) -> int:
    universe = load_universe(args.universe)
    instruments = args.instruments or list(universe.all_instruments)
    default_start = _parse_utc_date(args.start or DEFAULT_HISTORY_START)
    end_ms = _parse_utc_date(args.end) if args.end else None

    client = OkxPublicClient()
    failed = False
    with Store(args.db) as store:
        for inst_id in instruments:
            if args.start or args.full:
                start_ms = default_start
            else:
                start_ms = incremental_start(store, inst_id, BASE_TIMEFRAME, default_start)
            try:
                outcome = sync_ohlcv(
                    client, store, inst_id, start_ms=start_ms, end_ms=end_ms
                )
            except Exception as exc:  # noqa: BLE001 - reported per instrument
                print(f"{inst_id:<18} FAILED: {type(exc).__name__}: {exc}")
                failed = True
                continue
            span = "-"
            if outcome.oldest_ts is not None and outcome.newest_ts is not None:
                span = f"{_fmt(outcome.oldest_ts)} .. {_fmt(outcome.newest_ts)}"
            print(
                f"{inst_id:<18}{outcome.result.new:>8} new /{outcome.result.seen:>8} seen  "
                f"{span}  (dropped {outcome.skipped_unclosed} unclosed)"
            )
    return 1 if failed else 0


def cmd_quality(args: argparse.Namespace) -> int:
    universe = load_universe(args.universe)
    unclean = False
    with Store(args.db) as store:
        for inst_id in universe.all_instruments:
            frame = _frame_for(store, inst_id, args.timeframe)
            report = check_ohlcv(frame, inst_id, args.timeframe)
            print(report.summary())
            for gap in report.gaps[: args.show_gaps]:
                print(f"    gap: {gap}")
            if len(report.gaps) > args.show_gaps:
                print(f"    ... {len(report.gaps) - args.show_gaps} more gaps")
            unclean |= not report.clean
    return 1 if unclean else 0


def _frame_for(store: Store, inst_id: str, timeframe: str) -> pd.DataFrame:
    """Stored bars at `timeframe`, derived from the base if not stored.

    Only 1h is ever fetched, so querying the `ohlcv` table for 4h returns
    nothing at all — and an empty frame used to be reported as a clean series
    with no data, which reads as "4h is fine" rather than "4h was never
    checked".
    """
    if timeframe == BASE_TIMEFRAME:
        return store.load_ohlcv(inst_id, timeframe)
    return resample(store.load_ohlcv(inst_id, BASE_TIMEFRAME), timeframe)


def _parse_utc_date(text: str) -> int:
    parsed = dt.datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=dt.UTC)
    return int(parsed.timestamp() * 1000)


def cmd_coverage(args: argparse.Namespace) -> int:
    universe = load_universe(args.universe)
    now_ms = int(dt.datetime.now(dt.UTC).timestamp() * 1000)
    with Store(args.db) as store:
        print(f"{'series':<24}{'rows':>7}  {'oldest':<17}{'newest':<17}{'lag':>10}")
        print("-" * 76)
        for inst_id in universe.all_instruments:
            # Every stored timeframe, not just the base: a series fetched at 5m
            # was previously absent from coverage entirely. The base line is
            # kept even when nothing is stored so an instrument that has never
            # been synced still reports "never" rather than vanishing.
            timeframes = set(store.ohlcv_timeframes(inst_id)) | {BASE_TIMEFRAME}
            for timeframe in sorted(timeframes, key=duration_ms):
                count, lo, hi = store.ohlcv_coverage(inst_id, timeframe)
                print(_coverage_line(f"{timeframe:<3} {inst_id}", count, lo, hi, now_ms))
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
