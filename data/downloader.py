"""Historical OHLCV data downloader for CryptoQuant platform.

Combines OKXClient (API + pagination), SQLiteRepository (storage),
and validation (data quality) into a single download workflow.

Download modes:
  - incremental (default): fetch new data after the latest stored timestamp
  - full: re-download from the specified start date
  - backfill: extend history backwards before the earliest stored timestamp

Usage:
    python -m data.downloader --pair BTC/USDT --timeframe 1h --days 365
    python -m data.downloader --pair ETH/USDT --timeframe 4h --since 2024-01-01
    python -m data.downloader --pair BTC/USDT --timeframe 1h --full --sandbox
    python -m data.downloader --pair BTC/USDT --timeframe 1h --backfill 180
    python -m data.downloader --pair BTC/USDT --timeframe 1h --backfill
"""

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import structlog
from dotenv import load_dotenv

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

from data.manager import OKXClient
from data.models import OHLCVCandle
from data.repository import get_repository, reset_repository
from data.validation import validate_candles_batch

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class DownloadResult:
    """Result of a single download operation."""

    pair: str
    timeframe: str
    total_fetched: int
    valid_count: int
    rejected_count: int
    start_time: str   # human-readable
    end_time: str     # human-readable
    mode: str         # "incremental" | "full" | "backfill"

    def __str__(self) -> str:
        return (
            f"DownloadResult({self.pair}/{self.timeframe} "
            f"[{self.mode}]: "
            f"fetched={self.total_fetched} valid={self.valid_count} "
            f"rejected={self.rejected_count} "
            f"range={self.start_time} ~ {self.end_time})"
        )


def _empty_result(pair: str, timeframe: str, mode: str) -> DownloadResult:
    """Build a result for the case where no new data was found."""
    return DownloadResult(
        pair=pair,
        timeframe=timeframe,
        total_fetched=0,
        valid_count=0,
        rejected_count=0,
        start_time="N/A",
        end_time="N/A",
        mode=mode,
    )


def download(
    pair: str,
    timeframe: str = "1h",
    days: int = 365,
    since: Optional[str] = None,
    incremental: bool = True,
    backfill: Optional[int] = None,
    sandbox: bool = True,
) -> DownloadResult:
    """Download historical OHLCV data and save to SQLite.

    Three download modes:
      - incremental (default): fetch data after the latest stored timestamp
      - full (--full flag): re-download from the specified start date
      - backfill (--backfill N): extend history N days before the earliest
        stored timestamp

    Args:
        pair: Trading pair (e.g., "BTC/USDT")
        timeframe: Candle timeframe (e.g., "1h", "4h", "1d")
        days: Number of days to fetch (default 365, ignored if since is set)
        since: Start date as "YYYY-MM-DD" (overrides --days)
        incremental: Only fetch data after the latest stored timestamp
        backfill: Number of days to extend backwards (None = not requested,
            -1 = unlimited, >0 = N days back)
        sandbox: Use OKX sandbox environment

    Returns:
        DownloadResult with download statistics

    Raises:
        ValueError: If parameters are invalid or incompatible
    """
    repo = get_repository()

    # ── Backfill mode ─────────────────────────────────────────────────
    if backfill is not None:
        return _download_backfill(repo, pair, timeframe, backfill, sandbox)

    # ── 1. Calculate target start time ────────────────────────────────
    if since:
        try:
            dt = datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            target_since_ms = int(dt.timestamp() * 1000)
        except ValueError:
            raise ValueError(f"Invalid date format: {since}. Use YYYY-MM-DD.")
    else:
        target_since_ms = int(
            (datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000
        )

    # ── 2. Determine actual start time (incremental vs full) ──────────
    mode = "full"
    actual_since_ms = target_since_ms

    if incremental:
        latest_ts = repo.get_latest_timestamp(pair, timeframe)
        if latest_ts is not None and latest_ts > target_since_ms:
            actual_since_ms = latest_ts + 1  # Start one ms after existing data
            mode = "incremental"
            latest_dt = datetime.fromtimestamp(latest_ts / 1000, tz=timezone.utc)
            logger.info(
                "download_incremental",
                pair=pair,
                timeframe=timeframe,
                existing_latest=latest_dt.isoformat(),
            )

    # ── 3. Fetch data from OKX ────────────────────────────────────────
    logger.info(
        "download_start",
        pair=pair,
        timeframe=timeframe,
        since_ms=actual_since_ms,
        mode=mode,
    )

    client = OKXClient(sandbox=sandbox)
    try:
        candles = client.fetch_ohlcv_history(
            symbol=pair,
            timeframe=timeframe,
            since=actual_since_ms,
        )
    finally:
        client.close()

    if not candles:
        logger.info("download_no_new_data", pair=pair, timeframe=timeframe)
        return _empty_result(pair, timeframe, mode)

    # ── 4. Validate ───────────────────────────────────────────────────
    valid, rejected = validate_candles_batch(candles)

    if rejected:
        logger.warning(
            "download_rejected_candles",
            pair=pair,
            timeframe=timeframe,
            rejected_count=len(rejected),
            sample_reasons=[r[1] for r in rejected[:3]],
        )

    # ── 5. Save to SQLite ─────────────────────────────────────────────
    if valid:
        repo.save_candles(valid, pair, timeframe)
        logger.info(
            "download_saved",
            pair=pair,
            timeframe=timeframe,
            count=len(valid),
        )

    # ── 6. Build result ───────────────────────────────────────────────
    first_ts = candles[0].timestamp
    last_ts = candles[-1].timestamp
    start_dt = datetime.fromtimestamp(first_ts / 1000, tz=timezone.utc)
    end_dt = datetime.fromtimestamp(last_ts / 1000, tz=timezone.utc)

    result = DownloadResult(
        pair=pair,
        timeframe=timeframe,
        total_fetched=len(candles),
        valid_count=len(valid),
        rejected_count=len(rejected),
        start_time=start_dt.strftime("%Y-%m-%d %H:%M UTC"),
        end_time=end_dt.strftime("%Y-%m-%d %H:%M UTC"),
        mode=mode,
    )

    logger.info("download_complete", result=str(result))
    return result


def _download_backfill(
    repo,
    pair: str,
    timeframe: str,
    backfill_days: int,
    sandbox: bool,
) -> DownloadResult:
    """Download older data before the earliest stored timestamp.

    Finds the earliest candle in the database, calculates a target start
    time N days before that, and fetches all candles in the range
    [target, earliest). Uses fetch_ohlcv_history's until parameter to
    avoid re-downloading existing data.

    Args:
        repo: DataRepository instance
        pair: Trading pair
        timeframe: Candle timeframe
        backfill_days: How many days to extend backwards
        sandbox: Use OKX sandbox environment

    Returns:
        DownloadResult with download statistics

    Raises:
        ValueError: If no existing data found (need data to backfill from)
    """
    mode = "backfill"

    earliest_ts = repo.get_earliest_timestamp(pair, timeframe)
    if earliest_ts is None:
        raise ValueError(
            f"No existing data for {pair}/{timeframe}. "
            f"Run a normal download first before using --backfill."
        )

    earliest_dt = datetime.fromtimestamp(earliest_ts / 1000, tz=timezone.utc)

    if backfill_days > 0:
        # Fixed number of days back
        target_since_dt = earliest_dt - timedelta(days=backfill_days)
    else:
        # Unlimited (--backfill without argument): go back to before any crypto exchange existed
        target_since_dt = datetime(2015, 1, 1, tzinfo=timezone.utc)

    target_since_ms = int(target_since_dt.timestamp() * 1000)

    # Don't re-fetch the earliest candle — stop one ms before it
    until_ms = earliest_ts - 1

    logger.info(
        "download_backfill_start",
        pair=pair,
        timeframe=timeframe,
        existing_earliest=earliest_dt.isoformat(),
        target_since=target_since_dt.isoformat(),
        backfill_days=backfill_days,
    )

    client = OKXClient(sandbox=sandbox)
    try:
        candles = client.fetch_ohlcv_history(
            symbol=pair,
            timeframe=timeframe,
            since=target_since_ms,
            until=until_ms,
        )
    finally:
        client.close()

    if not candles:
        logger.info("download_backfill_no_data", pair=pair, timeframe=timeframe)
        return _empty_result(pair, timeframe, mode)

    # Validate
    valid, rejected = validate_candles_batch(candles)

    if rejected:
        logger.warning(
            "download_rejected_candles",
            pair=pair,
            timeframe=timeframe,
            rejected_count=len(rejected),
            sample_reasons=[r[1] for r in rejected[:3]],
        )

    # Save
    if valid:
        repo.save_candles(valid, pair, timeframe)
        logger.info(
            "download_saved",
            pair=pair,
            timeframe=timeframe,
            count=len(valid),
        )

    # Build result
    first_ts = candles[0].timestamp
    last_ts = candles[-1].timestamp
    start_dt = datetime.fromtimestamp(first_ts / 1000, tz=timezone.utc)
    end_dt = datetime.fromtimestamp(last_ts / 1000, tz=timezone.utc)

    result = DownloadResult(
        pair=pair,
        timeframe=timeframe,
        total_fetched=len(candles),
        valid_count=len(valid),
        rejected_count=len(rejected),
        start_time=start_dt.strftime("%Y-%m-%d %H:%M UTC"),
        end_time=end_dt.strftime("%Y-%m-%d %H:%M UTC"),
        mode=mode,
    )

    logger.info("download_backfill_complete", result=str(result))
    return result


# ── CLI Entry Point ───────────────────────────────────────────────────

def _print_result(result: DownloadResult) -> None:
    """Print a human-readable summary to stdout."""
    print(f"\n{'=' * 50}")
    print(f"  Download: {result.pair} / {result.timeframe} [{result.mode.upper()}]")
    print(f"{'=' * 50}")
    print(f"  Fetched:   {result.total_fetched} candles")
    print(f"  Valid:     {result.valid_count}")
    print(f"  Rejected:  {result.rejected_count}")
    print(f"  Range:     {result.start_time}  ->  {result.end_time}")

    if result.valid_count > 0:
        print(f"  Status:    OK")
    elif result.total_fetched == 0:
        print(f"  Status:    No new data (already up to date)")
    else:
        print(f"  Status:    All candles rejected (check data quality)")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download historical OHLCV data from OKX",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  python -m data.downloader --pair BTC/USDT --timeframe 1h --days 365
  python -m data.downloader --pair ETH/USDT --timeframe 4h --since 2024-01-01
  python -m data.downloader --pair BTC/USDT --timeframe 1h --full --sandbox
  python -m data.downloader --pair BTC/USDT --timeframe 1h --backfill 180
  python -m data.downloader --pair BTC/USDT --timeframe 1h --backfill
""",
    )
    parser.add_argument(
        "--pair", type=str, required=True,
        help="Trading pair (e.g., BTC/USDT, ETH/USDT)",
    )
    parser.add_argument(
        "--timeframe", type=str, default="1h",
        help="Candle timeframe (default: 1h)",
    )
    parser.add_argument(
        "--days", type=int, default=365,
        help="Number of days to fetch (default: 365)",
    )
    parser.add_argument(
        "--since", type=str, metavar="YYYY-MM-DD",
        help="Start date (overrides --days)",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--incremental", action="store_true", default=True,
        help="Only fetch new data after latest stored (default)",
    )
    group.add_argument(
        "--full", action="store_true",
        help="Re-download from the specified start date",
    )
    group.add_argument(
        "--backfill", type=int, nargs='?', const=-1, metavar="N",
        help="Extend history backwards. --backfill alone = fill until no more data; --backfill N = N days back",
    )
    parser.add_argument(
        "--sandbox", action="store_true", default=True,
        help="Use OKX sandbox environment (default: true)",
    )
    parser.add_argument(
        "--no-sandbox", action="store_false", dest="sandbox",
        help="Use OKX production environment",
    )
    args = parser.parse_args()

    try:
        result = download(
            pair=args.pair,
            timeframe=args.timeframe,
            days=args.days,
            since=args.since,
            incremental=not args.full and args.backfill is None,
            backfill=args.backfill,
            sandbox=args.sandbox,
        )
        _print_result(result)
        return 0
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        logger.error("download_failed", error=str(e))
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
