"""Data migration script - migrate from Parquet files to database."""

import sys
from pathlib import Path

import pandas as pd
import structlog

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.database import init_database
from data.loader import save_candles
from data.models import OHLCVCandle
from data.storage import load_historical_data

logger = structlog.get_logger(__name__)


def migrate_pair(pair: str, timeframe: str) -> int:
    """Migrate single pair/timeframe from Parquet to database."""
    try:
        df = load_historical_data(pair, timeframe)
        
        candles = [
            OHLCVCandle(
                timestamp=row["timestamp"],
                open_price=row["open"],
                high_price=row["high"],
                low_price=row["low"],
                close_price=row["close"],
                volume=row["volume"],
                pair=pair,
                timeframe=timeframe,
            )
            for _, row in df.iterrows()
        ]
        
        count = save_candles(candles, pair, timeframe)
        logger.info("Migrated", pair=pair, timeframe=timeframe, count=count)
        return count
        
    except FileNotFoundError:
        logger.warning("File not found", pair=pair, timeframe=timeframe)
        return 0
    except Exception as e:
        logger.error("Migration failed", pair=pair, timeframe=timeframe, error=str(e))
        return 0


def main():
    print("=" * 60)
    print("Data Migration: Parquet → Database")
    print("=" * 60)
    
    init_database()
    
    pairs = ["BTC/USDT", "ETH/USDT"]
    timeframes = ["15m", "1h", "4h", "1d"]
    
    total = 0
    
    for pair in pairs:
        for timeframe in timeframes:
            print(f"\nMigrating {pair} {timeframe}...")
            count = migrate_pair(pair, timeframe)
            total += count
            print(f"  Migrated {count} candles")
    
    print("\n" + "=" * 60)
    print(f"✓ Migration complete! Total: {total} candles")
    print("=" * 60)


if __name__ == "__main__":
    main()
