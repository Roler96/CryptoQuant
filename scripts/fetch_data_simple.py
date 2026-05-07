#!/usr/bin/env python3
"""Simple BTC/USDT data fetcher using OKX REST API directly.

No external dependencies required - uses only standard library + requests.
"""

import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.utils.datetime_utils import convert_to_utc8_str

# Try to import requests, fallback to urllib
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    import urllib.request
    import urllib.error
    HAS_REQUESTS = False

# Configuration
DATA_DIR = Path("data/historical")
DB_PATH = Path("data/cryptoquant.db")

# OKX API endpoints
OKX_BASE_URL = "https://www.okx.com"
SANDBOX_URL = "https://www.okx.com"  # Sandbox uses same endpoint for public data

# Timeframe mapping: OKX uses different format
def get_bar_size(timeframe: str) -> str:
    """Convert timeframe to OKX bar size."""
    mapping = {
        "1m": "1m",
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1h": "1H",
        "2h": "2H",
        "4h": "4H",
        "6h": "6H",
        "8h": "8H",
        "12h": "12H",
        "1d": "1D",
        "3d": "3D",
        "1w": "1W",
        "1M": "1M",
    }
    return mapping.get(timeframe, timeframe)


def fetch_candles_http(symbol: str, bar: str, after: str = "", before: str = "", limit: str = "100"):
    inst_id = symbol.replace("/", "-")

    url = f"{OKX_BASE_URL}/api/v5/market/history-candles"
    params = {
        "instId": inst_id,
        "bar": bar,
        "limit": limit,
    }
    if after:
        params["after"] = after
    if before:
        params["before"] = before

    if HAS_REQUESTS:
        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"HTTP error: {e}")
            return None
    else:
        # Use urllib
        query = "&".join(f"{k}={v}" for k, v in params.items())
        full_url = f"{url}?{query}"
        try:
            with urllib.request.urlopen(full_url, timeout=30) as response:
                data = response.read().decode('utf-8')
                return json.loads(data)
        except Exception as e:
            print(f"HTTP error: {e}")
            return None


def parse_candle(candle: list, symbol: str, timeframe: str) -> dict:
    """Parse OKX candle format to dict."""
    # OKX format: [ts, o, h, l, c, vol, volCcy]
    return {
        "timestamp": int(candle[0]),
        "open": Decimal(str(candle[1])),
        "high": Decimal(str(candle[2])),
        "low": Decimal(str(candle[3])),
        "close": Decimal(str(candle[4])),
        "volume": Decimal(str(candle[5])),
        "pair": symbol,
        "timeframe": timeframe,
    }


def init_database():
    """Initialize SQLite database."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS candles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            datetime_utc8 TEXT,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL,
            pair TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(timestamp, pair, timeframe)
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_candles_pair_tf_ts
        ON candles(pair, timeframe, timestamp)
    """)

    conn.commit()
    conn.close()
    print(f"Database initialized: {DB_PATH}")


def save_candles_to_db(candles: list, pair: str, timeframe: str):
    """Save candles to database."""
    if not candles:
        return 0

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    inserted = 0
    for candle in candles:
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO candles
                (timestamp, datetime_utc8, open, high, low, close, volume, pair, timeframe)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                candle["timestamp"],
                convert_to_utc8_str(candle["timestamp"]),
                float(candle["open"]),
                float(candle["high"]),
                float(candle["low"]),
                float(candle["close"]),
                float(candle["volume"]),
                candle["pair"],
                candle["timeframe"],
            ))
            inserted += 1
        except Exception as e:
            print(f"Error inserting candle: {e}")

    conn.commit()
    conn.close()
    return inserted


def get_latest_timestamp(pair: str, timeframe: str) -> int:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(timestamp) FROM candles WHERE pair = ? AND timeframe = ?", (pair, timeframe))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result[0] else 0


def get_earliest_timestamp(pair: str, timeframe: str) -> int:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT MIN(timestamp) FROM candles WHERE pair = ? AND timeframe = ?", (pair, timeframe))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result[0] else 0


def get_candles_count(pair: str, timeframe: str) -> int:
    """Get total candles count."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COUNT(*) FROM candles
        WHERE pair = ? AND timeframe = ?
    """, (pair, timeframe))

    result = cursor.fetchone()
    conn.close()

    return result[0] if result[0] else 0


def fetch_all_candles(symbol: str, timeframe: str, days: int = 365):
    """Fetch all candles for a symbol and timeframe."""
    bar = get_bar_size(timeframe)
    print(f"\n{'='*60}")
    print(f"Fetching {symbol} {timeframe} data ({days} days)")
    print(f"{'='*60}")

    # Check existing data
    existing_count = get_candles_count(symbol, timeframe)
    if existing_count > 0:
        min_ts = get_earliest_timestamp(symbol, timeframe)
        max_ts = get_latest_timestamp(symbol, timeframe)
        print(f"Existing data: {existing_count} candles")
        print(f"  Range: {min_ts} to {max_ts}")
        # Fetch older data (before the earliest)
        before_ts = str(min_ts)
        mode = "older"
    else:
        # No existing data, fetch from now backwards
        now = datetime.now(timezone.utc)
        before_ts = str(int(now.timestamp() * 1000))
        mode = "new"
        print(f"No existing data, fetching from now backwards")

    total_fetched = 0
    batch_num = 0

    while True:
        batch_num += 1
        print(f"\nBatch {batch_num}: fetching before {before_ts}...")

        result = fetch_candles_http(symbol, bar, before=before_ts, limit="100")

        if not result or result.get("code") != "0":
            error_msg = result.get("msg", "Unknown error") if result else "No response"
            print(f"API Error: {error_msg}")
            break

        data = result.get("data", [])
        if not data:
            print("No more data available")
            break

        candles = [parse_candle(c, symbol, timeframe) for c in data]
        saved = save_candles_to_db(candles, symbol, timeframe)
        total_fetched += saved

        print(f"Fetched {len(candles)} candles, saved {saved}")

        before_ts = str(candles[-1]["timestamp"])

        time.sleep(0.1)

        if total_fetched >= 50000:
            print("\n" + "="*60)
            print(f"Completed batch: {total_fetched} candles fetched")
            print("Run again to fetch older data (resumes automatically)")
            print("="*60)
            break

    print(f"\n{'='*60}")
    print(f"Total: Fetched {total_fetched} candles")
    print(f"{'='*60}")

    return total_fetched


def main():
    """Main entry point."""
    # Initialize database
    init_database()

    # Parse arguments
    import argparse
    parser = argparse.ArgumentParser(description="Fetch BTC/USDT historical data")
    parser.add_argument("--timeframe", default="1h", help="Timeframe (1m, 5m, 15m, 1h, 4h, 1d)")
    parser.add_argument("--days", type=int, default=365, help="Number of days to fetch")
    parser.add_argument("--all-timeframes", action="store_true", help="Fetch all common timeframes")

    args = parser.parse_args()

    symbol = "BTC/USDT"

    if args.all_timeframes:
        timeframes = ["1m", "5m", "15m", "1h", "4h", "1d"]
        for tf in timeframes:
            fetch_all_candles(symbol, tf, args.days)
            time.sleep(1)  # Rate limiting between timeframes
    else:
        fetch_all_candles(symbol, args.timeframe, args.days)

    # Show final stats
    print("\n" + "="*60)
    print("DATA SUMMARY")
    print("="*60)
    for tf in ["1m", "5m", "15m", "1h", "4h", "1d"]:
        count = get_candles_count(symbol, tf)
        if count > 0:
            print(f"{tf}: {count} candles")


if __name__ == "__main__":
    main()
