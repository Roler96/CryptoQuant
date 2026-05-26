"""Historical OHLCV data downloader for CryptoQuant platform.

Combines OKXClient (API + pagination), SQLiteRepository (storage),
and validation (data quality) into a single download workflow.

Downloads data within specified time range:
  - --start: If not specified, downloads from earliest available data
  - --end: If not specified, downloads until today

Usage:
    python -m data.downloader --pair BTC/USDT --timeframe 1h
    python -m data.downloader --pair ETH/USDT --timeframe 4h --start 2024-01-01 --end 2024-12-31
    python -m data.downloader --pair BTC/USDT --timeframe 1h --start 2024-01-01
    python -m data.downloader --pair BTC/USDT --timeframe 1h --end 2024-12-31
"""

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# Display timezone: UTC+8 (Asia/Shanghai)
TZ_UTC8 = timezone(timedelta(hours=8))

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


def _get_db_path(db_path: Optional[str] = None) -> Optional[str]:
    """Get database path from parameter, environment variable, or default.

    Priority:
    1. Explicit parameter (highest)
    2. DATABASE_URL environment variable
    3. Default: db/cryptoquant.db

    Args:
        db_path: Explicit database path parameter

    Returns:
        Database path string or None (to use default)
    """
    if db_path is not None:
        return db_path

    db_url = os.getenv("DATABASE_URL")
    if db_url:
        # Parse DATABASE_URL (e.g., "sqlite:///db/cryptoquant.db")
        if db_url.startswith("sqlite:///"):
            return db_url.replace("sqlite:///", "")
        else:
            return db_url

    return "db/cryptoquant.db"  # Default path


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

    def __str__(self) -> str:
        return (
            f"DownloadResult({self.pair}/{self.timeframe}: "
            f"fetched={self.total_fetched} valid={self.valid_count} "
            f"rejected={self.rejected_count} "
            f"range={self.start_time} ~ {self.end_time})"
        )


def _empty_result(pair: str, timeframe: str) -> DownloadResult:
    """Build a result for the case where no new data was found."""
    return DownloadResult(
        pair=pair,
        timeframe=timeframe,
        total_fetched=0,
        valid_count=0,
        rejected_count=0,
        start_time="N/A",
        end_time="N/A",
    )


def download(
    pair: str,
    timeframe: str = "1h",
    start: Optional[str] = None,
    end: Optional[str] = None,
    update: bool = False,
    db_path: Optional[str] = None,
    sandbox: bool = False,
) -> DownloadResult:
    """Download historical OHLCV data and save to SQLite.

    Two download modes:
      - update mode (--update): fetch data from latest stored timestamp to today
      - range mode (default): download data within specified time range

    Args:
        pair: Trading pair (e.g., "BTC/USDT")
        timeframe: Candle timeframe (e.g., "1h", "4h", "1d")
        start: Start date as "YYYY-MM-DD" (default: earliest available data)
        end: End date as "YYYY-MM-DD" (default: today)
        update: Update mode - fetch from latest stored timestamp to today
        db_path: SQLite database path (optional, reads from DATABASE_URL env or uses default)
        sandbox: Use OKX sandbox environment (default: False, use production)

    Returns:
        DownloadResult with download statistics

    Raises:
        ValueError: If date format is invalid or no data found in update mode
    """
    # Get database path from parameter, env, or default
    actual_db_path = _get_db_path(db_path)
    repo = get_repository(db_path=actual_db_path)

    # Parse time range parameters
    since_ms = None
    until_ms = None

    if update:
        # Update mode: fetch from latest stored timestamp to today
        latest_ts = repo.get_latest_timestamp(pair, timeframe)
        if latest_ts is None:
            raise ValueError(
                f"No existing data for {pair}/{timeframe}. "
                f"Use --start to specify start date for initial download."
            )
        since_ms = latest_ts + 1  # Start one ms after existing data
        
        # End date: today
        end_dt = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = end_dt + timedelta(days=1)
        until_ms = int(end_dt.timestamp() * 1000) - 1
        
        latest_dt = datetime.fromtimestamp(latest_ts / 1000, tz=TZ_UTC8)
        logger.info(
            "download_update_start",
            pair=pair,
            timeframe=timeframe,
            existing_latest=latest_dt.isoformat(),
            end="today",
        )
    else:
        # Range mode: use specified time range
        # Parse start date (default: get earliest valid timestamp from server)
        if start:
            try:
                start_dt = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                since_ms = int(start_dt.timestamp() * 1000)
            except ValueError:
                raise ValueError(f"Invalid start date format: {start}. Use YYYY-MM-DD.")
        else:
            # Get earliest valid timestamp from server
            client = OKXClient(sandbox=sandbox)
            try:
                since_ms = client.get_earliest_valid_timestamp(pair, timeframe)
                if since_ms is None:
                    raise ValueError(
                        f"Unable to determine earliest valid timestamp for {pair}/{timeframe}. "
                        f"Please specify --start date manually."
                    )
            finally:
                client.close()

        # Parse end date (default: today)
        if end:
            try:
                end_dt = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                raise ValueError(f"Invalid end date format: {end}. Use YYYY-MM-DD.")
        else:
            # Default to today
            end_dt = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        # End date inclusive: add 1 day to include the end date's candles
        end_dt = end_dt + timedelta(days=1)
        until_ms = int(end_dt.timestamp() * 1000) - 1

        logger.info(
            "download_range_start",
            pair=pair,
            timeframe=timeframe,
            start=start or "earliest (from server)",
            end=end or "today",
        )

    # Fetch data from OKX
    client = OKXClient(sandbox=sandbox)
    try:
        candles = client.fetch_ohlcv_history(
            symbol=pair,
            timeframe=timeframe,
            since=since_ms,
            until=until_ms,
        )
    finally:
        client.close()

    if not candles:
        logger.info("download_no_new_data", pair=pair, timeframe=timeframe, mode=mode)
        return _empty_result(pair, timeframe)

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

    # Save to SQLite
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
    start_dt = datetime.fromtimestamp(first_ts / 1000, tz=TZ_UTC8)
    end_dt = datetime.fromtimestamp(last_ts / 1000, tz=TZ_UTC8)

    result = DownloadResult(
        pair=pair,
        timeframe=timeframe,
        total_fetched=len(candles),
        valid_count=len(valid),
        rejected_count=len(rejected),
        start_time=start_dt.strftime("%Y-%m-%d %H:%M UTC+8"),
        end_time=end_dt.strftime("%Y-%m-%d %H:%M UTC+8"),
    )

    logger.info("download_complete", result=str(result))
    return result


# ── CLI Entry Point ───────────────────────────────────────────────────

def _print_result(result: DownloadResult) -> None:
    """Print a human-readable summary to stdout."""
    print(f"\n{'=' * 50}")
    print(f"  Download: {result.pair} / {result.timeframe}")
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
  # Download all available data (earliest to today)
  python -m data.downloader --pair BTC/USDT --timeframe 1h
  python -m data.downloader --pair ETH/USDT --timeframe 4h

  # Update data (from latest stored to today)
  python -m data.downloader --pair BTC/USDT --timeframe 1h --update

  # Download with specific time range
  python -m data.downloader --pair BTC/USDT --timeframe 1h --start 2024-01-01 --end 2024-12-31
  python -m data.downloader --pair BTC/USDT --timeframe 1h --start 2024-01-01
  python -m data.downloader --pair BTC/USDT --timeframe 1h --end 2024-12-31
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
    
    # Create mutually exclusive group for update vs range mode
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--update", action="store_true",
        help="Update mode: fetch data from latest stored timestamp to today",
    )
    group.add_argument(
        "--start", type=str, metavar="YYYY-MM-DD",
        help="Start date (default: earliest available data)",
    )
    
    parser.add_argument(
        "--end", type=str, metavar="YYYY-MM-DD",
        help="End date (default: today, inclusive)",
    )
    parser.add_argument(
        "--db", type=str, metavar="PATH",
        help="SQLite database path (default: reads from DATABASE_URL env or uses db/cryptoquant.db)",
    )
    parser.add_argument(
        "--sandbox", action="store_true", default=False,
        help="Use OKX sandbox environment (default: False, use production)",
    )
    args = parser.parse_args()

    try:
        result = download(
            pair=args.pair,
            timeframe=args.timeframe,
            start=args.start,
            end=args.end,
            update=args.update,
            db_path=args.db,
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