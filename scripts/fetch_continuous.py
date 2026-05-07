#!/usr/bin/env python3
"""Continuously fetch data until reaching target date."""

import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import requests

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.utils.datetime_utils import convert_to_utc8_str

DATA_DIR = Path("data/historical")
DB_PATH = Path("data/cryptoquant.db")
OKX_BASE_URL = "https://www.okx.com"

def get_bar_size(timeframe: str) -> str:
    mapping = {
        "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
        "1h": "1H", "2h": "2H", "4h": "4H", "6h": "6H",
        "8h": "8H", "12h": "12H", "1d": "1D", "3d": "3D",
        "1w": "1W", "1M": "1M",
    }
    return mapping.get(timeframe, timeframe)

def fetch_candles(symbol: str, bar: str, before: str = "", limit: str = "100"):
    inst_id = symbol.replace("/", "-")
    url = f"{OKX_BASE_URL}/api/v5/market/history-candles"
    params = {"instId": inst_id, "bar": bar, "limit": limit}
    if before:
        params["before"] = before
    
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"HTTP error: {e}")
        return None

def parse_candle(candle: list, symbol: str, timeframe: str) -> dict:
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

def save_candles(candles: list, pair: str, timeframe: str) -> int:
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
            print(f"Insert error: {e}")
    
    conn.commit()
    conn.close()
    return inserted

def get_stats(pair: str, timeframe: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT MIN(timestamp), MAX(timestamp), COUNT(*) 
        FROM candles WHERE pair = ? AND timeframe = ?
    """, (pair, timeframe))
    result = cursor.fetchone()
    conn.close()
    return result

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair", default="BTC/USDT")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--target-year", type=int, default=2017)
    parser.add_argument("--batches", type=int, default=100)
    args = parser.parse_args()
    
    symbol = args.pair
    timeframe = args.timeframe
    target_ts = int(datetime(args.target_year, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    
    print(f"Fetching {symbol} {timeframe} data until {args.target_year}")
    print(f"Target timestamp: {target_ts}")
    
    bar = get_bar_size(timeframe)
    min_ts, max_ts, count = get_stats(symbol, timeframe)
    
    if min_ts:
        print(f"Current range: {min_ts} to {max_ts}, count: {count}")
        before_ts = str(min_ts)
    else:
        print("No existing data, starting from now")
        before_ts = str(int(datetime.now(timezone.utc).timestamp() * 1000))
    
    total_fetched = 0
    
    for batch in range(args.batches):
        result = fetch_candles(symbol, bar, before=before_ts, limit="100")
        
        if not result or result.get("code") != "0":
            print(f"API error: {result}")
            break
        
        data = result.get("data", [])
        if not data:
            print("No more data")
            break
        
        candles = [parse_candle(c, symbol, timeframe) for c in data]
        saved = save_candles(candles, symbol, timeframe)
        total_fetched += saved
        
        oldest_ts = candles[-1]["timestamp"]
        before_ts = str(oldest_ts)
        
        print(f"Batch {batch+1}: saved {saved} candles, oldest: {oldest_ts} ({datetime.fromtimestamp(oldest_ts/1000, tz=timezone.utc).isoformat()})")
        
        if oldest_ts <= target_ts:
            print(f"Reached target year {args.target_year}!")
            break
        
        time.sleep(0.1)
    
    min_ts, max_ts, count = get_stats(symbol, timeframe)
    print(f"\nFinal stats: {count} candles from {min_ts} to {max_ts}")
    print(f"Total fetched: {total_fetched}")

if __name__ == "__main__":
    main()
